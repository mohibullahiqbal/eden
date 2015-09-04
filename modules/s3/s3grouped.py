# -*- coding: utf-8 -*-

""" S3 Grouped Items Report Method

    @copyright: 2015 (c) Sahana Software Foundation
    @license: MIT

    Permission is hereby granted, free of charge, to any person
    obtaining a copy of this software and associated documentation
    files (the "Software"), to deal in the Software without
    restriction, including without limitation the rights to use,
    copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following
    conditions:

    The above copyright notice and this permission notice shall be
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
    OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
    HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
    WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
    OTHER DEALINGS IN THE SOFTWARE.

    @status: experimental
"""

__all__ = ("S3GroupedItemsReport",
           )

import math
import sys

try:
    import json # try stdlib (Python 2.6)
except ImportError:
    try:
        import simplejson as json # try external module
    except ImportError:
        import gluon.contrib.simplejson as json # fallback to pure-Python module

from gluon import current

from s3rest import S3Method
from s3utils import s3_unicode

# Compact JSON encoding
SEPARATORS = (",", ":")

# =============================================================================
class S3GroupedItemsReport(S3Method):
    """
        REST Method Handler for Grouped Items Reports

        @todo: page method
        @todo: filter form and ajax method
        @todo: widget method
        @todo: config and URL options, defaults
    """

    # -------------------------------------------------------------------------
    def apply_method(self, r, **attr):
        """
            Page-render entry point for REST interface.

            @param r: the S3Request instance
            @param attr: controller attributes
        """

        output = {}
        if r.http == "GET":
            return self.report(r, **attr)
        else:
            r.error(405, current.ERROR.BAD_METHOD)
        return output

    # -------------------------------------------------------------------------
    def widget(self, r, method=None, widget_id=None, visible=True, **attr):
        """
            Summary widget method

            @param r: the S3Request
            @param method: the widget method
            @param widget_id: the widget ID
            @param visible: whether the widget is initially visible
            @param attr: controller attributes
        """

        output = {}
        if r.http == "GET":
            r.error(405, current.ERROR.NOT_IMPLEMENTED)
        else:
            r.error(405, current.ERROR.BAD_METHOD)
        return output

    # -------------------------------------------------------------------------
    def report(self, r, **attr):
        """
            Report generator

            @param r: the S3Request instance
            @param attr: controller attributes
        """

        output = {}

        # Get the report configuration
        report_config = self.get_report_config()

        # Resolve selectors in the report configuration
        fields = self.resolve(report_config)

        # Get extraction method
        extract = report_config.get("extract")
        if not callable(extract):
            extract = self.extract

        selectors = [s for s in fields if fields[s] is not None]
        orderby = report_config.get("orderby_cols")

        # Extract the data
        items = extract(self.resource, selectors, orderby)

        # Group and aggregate
        groupby = report_config.get("groupby_cols")
        aggregate = report_config.get("aggregate_cols")

        gi = S3GroupedItems(items, groupby=groupby, aggregate=aggregate)

        # Generate JSON data
        display_cols = report_config.get("display_cols")
        labels = report_config.get("labels")
        represent = report_config.get("groupby_represent")
        data = gi.json(fields=display_cols,
                       labels=labels,
                       represent=represent,
                       )
        #print data

        # Widget ID
        widget_id = "groupeditems"

        # Render output
        if r.representation in ("html", "iframe"):
            # Page load

            output["report_type"] = "groupeditems"
            output["widget_id"] = widget_id

            # Report title
            title = report_config.get("title")
            if title is None:
                tablename = self.resource.tablename
                title = self.crud_string(tablename, "title_report")
            output["title"] = title

            # Inject data
            # @todo

            # Empty section
            output["empty"] = current.T("No data available")

            # Inject script
            options = {}
            self.inject_script(widget_id, options=options)

            # Detect and store theme-specific inner layout
            self._view(r, "grouped.html")

            # View
            response = current.response
            response.view = self._view(r, "report.html")

        # @todo: implement
        #elif r.representation == "json":
            ## Ajax load
            #output = json.dumps(data, separators=SEPARATORS)

        else:
            r.error(501, current.ERROR.BAD_FORMAT)

        return output

    # -------------------------------------------------------------------------
    def get_report_config(self):
        """
            Get the configuration for the requested report, updated
            with URL options
        """

        r = self.request
        get_vars = r.get_vars

        # Get the resource configuration
        config = self.resource.get_config("grouped")
        if not config:
            # No reports implemented for this resource
            r.error(405, current.ERROR.NOT_IMPLEMENTED)

        # Which report?
        report = get_vars.get("report", "default")
        if isinstance(report, list):
            report = report[-1]

        # Get the report config
        report_config = config.get(report)
        if not report_config:
            # This report is not implemented
            r.error(405, current.ERROR.NOT_IMPLEMENTED)
        else:
            report_config = dict(report_config)

        # Orderby
        orderby = get_vars.get("orderby")
        if isinstance(orderby, list):
            orderby = ",".join(orderby).split(",")
        if not orderby:
            orderby = report_config.get("orderby")
        if not orderby:
            orderby = report_config.get("groupby")
        report_config["orderby"] = orderby

        return report_config

    # -------------------------------------------------------------------------
    def resolve(self, report_config):
        """
            Get all field selectors for the report, and resolve them
            against the resource

            @param resource: the resource
            @param config: the report config (will be updated)

            @return: a dict {selector: rfield}, where rfield can be None
                     if the selector does not resolve against the resource
        """

        resource = self.resource

        # Get selectors for visible fields
        fields = report_config.get("fields")
        if not fields:
            # Fall back to list_fields
            selectors = resource.list_fields("grouped_fields")
            fields = list(selectors)
        else:
            selectors = list(fields)

        # Get selectors for grouping axes
        groupby = report_config.get("groupby")
        if isinstance(groupby, (list, tuple)):
            selectors.extend(groupby)
        elif groupby:
            selectors.append(groupby)

        # Get selectors for aggregation
        aggregate = report_config.get("aggregate")
        if aggregate:
            for method, selector in aggregate:
                selectors.append(selector)

        # Get selectors for orderby
        orderby = report_config.get("orderby")
        if orderby:
            for selector in orderby:
                s, d = ("%s asc" % selector).split(" ")[:2]
            selectors.append(s)

        # Resolve all selectors against the resource
        rfields = {}
        labels = {}
        id_field = str(resource._id)
        for f in selectors:
            label, selector = f if type(f) is tuple else (None, f)
            if selector in rfields:
                # Already resolved
                continue
            try:
                rfield = resource.resolve_selector(selector)
            except (SyntaxError, AttributeError):
                rfield = None
            if label and rfield:
                rfield.label = label
            if id_field and rfield and rfield.colname == id_field:
                id_field = None
            rfields[selector] = rfield
            if rfield:
                labels[rfield.colname] = rfield.label
            elif label:
                labels[selector] = label
        report_config["labels"] = labels

        # Make sure id field is always included
        if id_field:
            id_name = resource._id.name
            rfields[id_name] = resource.resolve_selector(id_name)

        # Get column names for vsibile fields
        display_cols = []
        for f in fields:
            label, selector = f if type(f) is tuple else (None, f)
            rfield = rfields.get(selector)
            colname = rfield.colname if rfield else selector
            if colname:
                display_cols.append(colname)
        report_config["display_cols"] = display_cols

        # Get column names for orderby
        orderby_cols = []
        orderby = report_config.get("orderby")
        if orderby:
            for selector in orderby:
                s, d = ("%s asc" % selector).split(" ")[:2]
                rfield = rfields.get(s)
                colname = rfield.colname if rfield else None
                if colname:
                    orderby_cols.append("%s %s" % (colname, d))
        if not orderby_cols:
            orderby_cols = None
        report_config["orderby_cols"] = orderby_cols

        # Get column names for grouping
        groupby_cols = []
        groupby_represent = {}
        groupby = report_config.get("groupby")
        if groupby:
            for selector in groupby:
                rfield = rfields.get(selector)
                if rfield:
                    colname = rfield.colname
                    field = rfield.field
                    if field:
                        groupby_represent[colname] = field.represent
                else:
                    colname = selector
                groupby_cols.append(colname)
        report_config["groupby_cols"] = groupby_cols
        report_config["groupby_represent"] = groupby_represent

        # Get columns names for aggregation
        aggregate_cols = []
        aggregate = report_config.get("aggregate")
        if aggregate:
            for method, selector in aggregate:
                rfield = rfields.get(selector)
                colname = rfield.colname if rfield else selector
                aggregate_cols.append((method, colname))
        report_config["aggregate_cols"] = aggregate_cols

        return rfields

    # -------------------------------------------------------------------------
    @staticmethod
    def extract(resource, selectors, orderby):
        """
            Extract the data from the resource (default method, can be
            overridden in report config)

            @param resource: the resource
            @param selectors: the field selectors

            @returns: data dict {colname: value} including raw data (_row)
        """

        data = resource.select(selectors,
                               limit=None,
                               orderby=orderby,
                               raw_data = True,
                               represent = True,
                               )
        return data.rows

    # -------------------------------------------------------------------------
    @staticmethod
    def inject_script(widget_id, options=None):
        """
            Inject the groupedItems script and bind it to the container

            @param widget_id: the widget container DOM ID
            @param options: dict with options for the widget

            @note: options dict must be JSON-serializable
        """

        s3 = current.response.s3

        scripts = s3.scripts
        appname = current.request.application

        # Inject UI widget script
        if s3.debug:
            script = "/%s/static/scripts/S3/s3.ui.groupeditems.js" % appname
            if script not in scripts:
                scripts.append(script)
        else:
            script = "/%s/static/scripts/S3/s3.groupeditems.min.js" % appname
            if script not in scripts:
                scripts.append(script)

        # Inject widget instantiation
        if not options:
            options = {}
        script = """$("#%(widget_id)s").groupedItems(%(options)s)""" % \
                    {"widget_id": widget_id,
                     "options": json.dumps(options),
                     }
        s3.jquery_ready.append(script)

# =============================================================================
class S3GroupedItems(object):
    """
        Helper class representing dict-like items grouped by
        attribute values, used by S3GroupedItemsReport
    """

    def __init__(self, items, groupby=None, aggregate=None, values=None):
        """
            Constructor

            @param items: ordered iterable of items (e.g. list, tuple,
                          iterator, Rows), grouping tries to maintain
                          the original item order
            @param groupby: attribute key or ordered iterable of
                            attribute keys (e.g. list, tuple, iterator)
                            for the items to be grouped by; grouping
                            happens in order of appearance of the keys
            @param aggregate: aggregates to compute, list of tuples
                              (method, key)
            @param value: the grouping values for this group (internal)
        """

        self._groups_dict = {}
        self._groups_list = []

        self.values = values or {}

        self._aggregates = {}

        if groupby:
            if isinstance(groupby, basestring):
                # Single grouping key
                groupby = [groupby]
            else:
                groupby = list(groupby)

            self.key = groupby.pop(0)
            self.groupby = groupby
            self.items = None
            for item in items:
                self.add(item)
        else:
            self.key = None
            self.groupby = None
            self.items = list(items)

        if aggregate:
            if type(aggregate) is tuple:
                aggregate = [aggregate]
            for method, key in aggregate:
                self.aggregate(method, key)

    # -------------------------------------------------------------------------
    @property
    def groups(self):
        """ Generator for iteration over subgroups """

        groups = self._groups_dict
        for value in self._groups_list:
            yield groups.get(value)

    # -------------------------------------------------------------------------
    def __getitem__(self, key):
        """
            Getter for the grouping values dict

            @param key: the grouping key

        """

        if type(key) is tuple:
            return self.aggregate(key[0], key[1]).result
        else:
            return self.values.get(key)

    # -------------------------------------------------------------------------
    def add(self, item):
        """
            Add a new item, either to this group or to a subgroup

            @param item: the item
        """

        # Remove all aggregates
        if self._aggregates:
            self._aggregates = {}

        key = self.key
        if key:

            raw = item.get("_row")
            if raw is None:
                value = item.get(key)
            else:
                # Prefer raw values for grouping over representations
                try:
                    value = raw.get(key)
                except (AttributeError, TypeError):
                    # _row is not a dict
                    value = item.get(key)

            if type(value) is list:
                # list:type => item belongs into multiple groups
                add_to_group = self.add_to_group
                for v in value:
                    add_to_group(key, v, item)
            else:
                self.add_to_group(key, value, item)
        else:
            # No subgroups
            self.items.append(item)

    # -------------------------------------------------------------------------
    def add_to_group(self, key, value, item):
        """
            Add an item to a subgroup. Create that subgroup if it does not
            yet exist.

            @param key: the grouping key
            @param value: the grouping value for the subgroup
            @param item: the item to add to the subgroup
        """

        groups = self._groups_dict
        if value in groups:
            group = groups[value]
            group.add(item)
        else:
            values = dict(self.values)
            values[key] = value
            group = S3GroupedItems([item],
                                   groupby = self.groupby,
                                   values = values,
                                   )
            groups[value] = group
            self._groups_list.append(value)
        return group

    # -------------------------------------------------------------------------
    def get_values(self, key):
        """
            Get a list of attribute values for the items in this group

            @param key: the attribute key
            @return: the list of values
        """

        if self.items is None:
            return None

        values = []
        append = values.append
        extend = values.extend

        for item in self.items:

            raw = item.get("_row")
            if raw is None:
                # Prefer raw values for aggregation over representations
                value = item.get(key)
            else:
                try:
                    value = raw.get(key)
                except (AttributeError, TypeError):
                    # _row is not a dict
                    value = item.get(key)

            if type(value) is list:
                extend(value)
            else:
                append(value)
        return values

    # -------------------------------------------------------------------------
    def aggregate(self, method, key):
        """
            Aggregate item attribute values (recursively over subgroups)

            @param method: the aggregation method
            @param key: the attribute key

            @return: an S3GroupAggregate instance
        """

        aggregates = self._aggregates
        if (method, key) in aggregates:
            # Already computed
            return aggregates[(method, key)]

        if self.items is not None:
            # No subgroups => aggregate values in this group
            values = self.get_values(key)
            aggregate = S3GroupAggregate(method, key, values)
        else:
            # Aggregate recursively over subgroups
            combine = S3GroupAggregate.aggregate
            aggregate = combine(group.aggregate(method, key)
                                    for group in self.groups)

        # Store aggregate
        aggregates[(method, key)] = aggregate

        return aggregate

    # -------------------------------------------------------------------------
    def __repr__(self):
        """ Represent this group and all its subgroups as string """

        return self.__represent()

    # -------------------------------------------------------------------------
    def __represent(self, level=0):
        """
            Represent this group and all its subgroups as string

            @param level: the hierarchy level of this group (for indentation)
        """

        output = ""
        indent = " " * level

        aggregates = self._aggregates
        for aggregate in aggregates.values():
            output = "%s\n%s  %s(%s) = %s" % (output,
                                               indent,
                                               aggregate.method,
                                               aggregate.key,
                                               aggregate.result,
                                               )
        if aggregates:
            output = "%s\n" % output

        key = self.key
        if key:
            for group in self.groups:
                value = group[key]
                if group:
                    group_repr = group.__represent(level = level+1)
                else:
                    group_repr = "[empty group]"
                output = "%s\n%s=> %s: %s\n%s" % \
                         (output, indent, key, value, group_repr)
        else:
            for item in self.items:
                output = "%s\n%s  %s" % (output, indent, item)
            output = "%s\n" % output

        return output

    # -------------------------------------------------------------------------
    def json(self,
             fields=None,
             labels=None,
             represent=None,
             as_dict=False,
             master=True):
        """
            Serialize this group as JSON

            @param columns: the columns to include for each item
            @param labels: columns labels as dict {key: label},
                           including the labels for grouping axes
            @param represent: dict of representation methods for grouping
                              axis values {colname: function}
            @param as_dict: return output as dict rather than JSON string
            @param master: this is the top-level group (internal)
        """

        T = current.T

        output = {}

        if not fields:
            raise SyntaxError

        if master:
            # Add columns and grouping information to top level group
            if labels is None:
                labels = {}

            def check_label(colname):
                if colname in labels:
                    label = labels[colname] or ""
                else:
                    fname = colname.split(".", 1)[-1]
                    label = " ".join([s.strip().capitalize()
                                    for s in fname.split("_") if s])
                    label = labels[colname] = T(label)
                return str(label)

            grouping = []
            groupby = self.groupby
            if groupby:
                for axis in groupby:
                    check_label(axis)
                    grouping.append(axis)
            output["g"] = grouping

            columns = []
            for colname in fields:
                check_label(colname)
                columns.append(colname)
            output["c"] = columns

            output["l"] = dict((c, str(l)) for c, l in labels.items())

        key = self.key
        if key:
            output["k"] = key

            data = []
            add_group = data.append
            for group in self.groups:
                # Render subgroup
                gdict = group.json(fields, labels,
                                   represent = represent,
                                   as_dict = True,
                                   master = False,
                                   )

                # Add subgroup attribute value
                value = group[key]
                renderer = represent.get(key) if represent else None
                if renderer is None:
                    value = s3_unicode(value).encode("utf-8")
                else:
                    # @todo: call bulk-represent if available
                    value = s3_unicode(renderer(value)).encode("utf-8")
                gdict["v"] = value
                add_group(gdict)

            output["d"] = data
            output["i"] = None
        else:
            oitems = []
            add_item = oitems.append
            for item in self.items:
                # Render item
                oitem = {}
                for colname in fields:
                    if colname in item:
                        value = item[colname] or ""
                    else:
                        # Fall back to raw value
                        raw = item.get("_row")
                        try:
                            value = raw.get(colname)
                        except (AttributeError, TypeError):
                            # _row is not a dict
                            value = None
                    if value is None:
                        value = ""
                    else:
                        value = s3_unicode(value).encode("utf-8")
                    oitem[colname] = value
                add_item(oitem)

            output["d"] = None
            output["i"] = oitems

        # Convert to JSON unless requested otherwise
        if master and not as_dict:
            output = json.dumps(output, separators=SEPARATORS)
        return output

# =============================================================================
class S3GroupAggregate(object):
    """ Class representing aggregated values """

    def __init__(self, method, key, values):
        """
            Constructor

            @param method: the aggregation method (count, sum, min, max, avg)
            @param key: the attribute key
            @param values: the attribute values
        """

        self.method = method
        self.key = key

        self.values = values
        self.result = self.__compute(method, values)

    # -------------------------------------------------------------------------
    def __compute(self, method, values):
        """
            Compute the aggregated value

            @param method: the aggregation method
            @param values: the values

            @return: the aggregated value
        """

        if values is None:
            result = None
        else:
            try:
                values = [v for v in values if v is not None]
            except TypeError:
                result = None
            else:
                if method == "count":
                    result = len(set(values))
                elif method == "sum":
                    try:
                        result = math.fsum(values)
                    except (TypeError, ValueError):
                        result = None
                elif method == "min":
                    try:
                        result = min(values)
                    except (TypeError, ValueError):
                        result = None
                elif method == "max":
                    try:
                        result = max(values)
                    except (TypeError, ValueError):
                        result = None
                elif method == "avg":
                    num = len(values)
                    if num:
                        try:
                            result = sum(values) / float(num)
                        except (TypeError, ValueError):
                            result = None
                    else:
                        result = None
                else:
                    result = None
        return result

    # -------------------------------------------------------------------------
    @classmethod
    def aggregate(cls, items):
        """
            Combine sub-aggregates

            @param items: iterable of sub-aggregates

            @return: an S3GroupAggregate instance
        """

        method = None
        key = None
        values = []

        for item in items:

            if method is None:
                method = item.method
                key = item.key

            elif key != item.key or method != item.method:
                raise TypeError

            if item.values:
                values.extend(item.values)

        return cls(method, key, values)

# END =========================================================================