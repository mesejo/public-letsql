"""Ibis expression API definitions."""

from __future__ import annotations

import builtins
import datetime
import functools
import itertools
import numbers
import operator
from collections import Counter
from typing import TYPE_CHECKING, Any, overload

import xorq.vendor.ibis.expr.builders as bl
import xorq.vendor.ibis.expr.datatypes as dt
import xorq.vendor.ibis.expr.operations as ops
import xorq.vendor.ibis.expr.schema as sch
import xorq.vendor.ibis.expr.types as ir
from xorq.common.exceptions import XorqInputError
from xorq.vendor.ibis import selectors, util
from xorq.vendor.ibis.backends import BaseBackend, connect
from xorq.vendor.ibis.common.deferred import Deferred, _, deferrable
from xorq.vendor.ibis.common.dispatch import lazy_singledispatch
from xorq.vendor.ibis.common.grounds import Concrete
from xorq.vendor.ibis.common.temporal import normalize_datetime, normalize_timezone
from xorq.vendor.ibis.expr.decompile import decompile
from xorq.vendor.ibis.expr.schema import Schema
from xorq.vendor.ibis.expr.sql import parse_sql, to_sql
from xorq.vendor.ibis.expr.types import (
    Column,
    DateValue,
    Expr,
    Scalar,
    Table,
    TimestampValue,
    TimeValue,
    Value,
    array,
    literal,
    map,
    null,
    struct,
)
from xorq.vendor.ibis.util import experimental


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    import pandas as pd
    import polars as pl
    import pyarrow as pa

    from xorq.vendor.ibis.expr.schema import SchemaLike

__all__ = (
    "Column",
    "Deferred",
    "Expr",
    "Scalar",
    "Schema",
    "Table",
    "Value",
    "_",
    "aggregate",
    "and_",
    "array",
    "asc",
    "case",
    "coalesce",
    "connect",
    "cross_join",
    "cume_dist",
    "cumulative_window",
    "date",
    "decompile",
    "deferred",
    "dense_rank",
    "desc",
    "difference",
    "dtype",
    "e",
    "following",
    "geo_area",
    "geo_as_binary",
    "geo_as_ewkb",
    "geo_as_ewkt",
    "geo_as_text",
    "geo_azimuth",
    "geo_buffer",
    "geo_centroid",
    "geo_contains",
    "geo_contains_properly",
    "geo_covered_by",
    "geo_covers",
    "geo_crosses",
    "geo_d_fully_within",
    "geo_d_within",
    "geo_difference",
    "geo_disjoint",
    "geo_distance",
    "geo_end_point",
    "geo_envelope",
    "geo_equals",
    "geo_geometry_n",
    "geo_geometry_type",
    "geo_intersection",
    "geo_intersects",
    "geo_is_valid",
    "geo_length",
    "geo_line_locate_point",
    "geo_line_merge",
    "geo_line_substring",
    "geo_max_distance",
    "geo_n_points",
    "geo_n_rings",
    "geo_ordering_equals",
    "geo_overlaps",
    "geo_perimeter",
    "geo_point",
    "geo_point_n",
    "geo_simplify",
    "geo_srid",
    "geo_start_point",
    "geo_touches",
    "geo_transform",
    "geo_unary_union",
    "geo_union",
    "geo_within",
    "geo_x",
    "geo_x_max",
    "geo_x_min",
    "geo_y",
    "geo_y_max",
    "geo_y_min",
    "get_backend",
    "greatest",
    "ifelse",
    "infer_dtype",
    "infer_schema",
    "intersect",
    "interval",
    "join",
    "least",
    "literal",
    "map",
    "memtable",
    "negate",
    "now",
    "ntile",
    "null",
    "or_",
    "param",
    "parse_sql",
    "percent_rank",
    "pi",
    "preceding",
    "random",
    "range",
    "range_window",
    "rank",
    "read_csv",
    "read_delta",
    "read_json",
    "read_parquet",
    "row_number",
    "rows_window",
    "schema",
    "selectors",
    "set_backend",
    "struct",
    "table",
    "time",
    "timestamp",
    "to_sql",
    "today",
    "trailing_range_window",
    "trailing_window",
    "union",
    "uuid",
    "watermark",
    "where",
    "window",
)


dtype = dt.dtype
infer_dtype = dt.infer
infer_schema = sch.infer
aggregate = ir.Table.aggregate
cross_join = ir.Table.cross_join
join = ir.Table.join
asof_join = ir.Table.asof_join

e = ops.E().to_expr()
pi = ops.Pi().to_expr()


deferred = _
"""Deferred expression object.

Use this object to refer to a previous table expression in a chain of
expressions.

::: {.callout-note}
## `_` may conflict with other idioms in Python

See https://github.com/ibis-project/ibis/issues/4704 for details.

Use `from xorq.vendor.ibis import deferred as <NAME>` to assign a different name to
the deferred object builder.

Another option is to use `ibis._` directly.
:::

Examples
--------
>>> from ibis import _
>>> t = ibis.table(dict(key="int", value="float"), name="t")
>>> expr = t.group_by(key=_.key - 1).agg(total=_.value.sum())
>>> expr.schema()
ibis.Schema {
  key    int64
  total  float64
}
"""


def param(type: dt.DataType) -> ir.Scalar:
    """Create a deferred parameter of a given type.

    Parameters
    ----------
    type
        The type of the unbound parameter, e.g., double, int64, date, etc.

    Returns
    -------
    Scalar
        A scalar expression backend by a parameter

    Examples
    --------
    >>> from datetime import date
    >>> import ibis
    >>> start = ibis.param("date")
    >>> t = ibis.memtable(
    ...     {
    ...         "date_col": [date(2013, 1, 1), date(2013, 1, 2), date(2013, 1, 3)],
    ...         "value": [1.0, 2.0, 3.0],
    ...     },
    ... )
    >>> expr = t.filter(t.date_col >= start).value.sum()
    >>> expr.execute(params={start: date(2013, 1, 1)})
    np.float64(6.0)
    >>> expr.execute(params={start: date(2013, 1, 2)})
    np.float64(5.0)
    >>> expr.execute(params={start: date(2013, 1, 3)})
    np.float64(3.0)
    """
    return ops.ScalarParameter(type).to_expr()


def schema(
    pairs: SchemaLike | None = None,
    names: Iterable[str] | None = None,
    types: Iterable[str | dt.DataType] | None = None,
) -> sch.Schema:
    """Validate and return a [`Schema`](./schemas.qmd#ibis.expr.schema.Schema) object.

    Parameters
    ----------
    pairs
        List or dictionary of name, type pairs. Mutually exclusive with `names`
        and `types` arguments.
    names
        Field names. Mutually exclusive with `pairs`.
    types
        Field types. Mutually exclusive with `pairs`.

    Returns
    -------
    Schema
        An ibis schema

    Examples
    --------
    >>> from xorq.vendor.ibis import schema, Schema
    >>> sc = schema([("foo", "string"), ("bar", "int64"), ("baz", "boolean")])
    >>> sc = schema(names=["foo", "bar", "baz"], types=["string", "int64", "boolean"])
    >>> sc = schema(dict(foo="string"))
    >>> sc = schema(Schema(dict(foo="string")))  # no-op

    """
    if pairs is not None:
        return sch.schema(pairs)

    # validate lengths of names and types are the same
    if len(names) != len(types):
        raise ValueError("Schema names and types must have the same length")

    return sch.Schema.from_tuples(zip(names, types))


_table_names = (f"unbound_table_{i:d}" for i in itertools.count())


def table(
    schema: SchemaLike | None = None,
    name: str | None = None,
    catalog: str | None = None,
    database: str | None = None,
) -> ir.Table:
    """Create a table literal or an abstract table without data.

    Ibis uses the word database to refer to a collection of tables, and the word
    catalog to refer to a collection of databases. You can use a combination of
    `catalog` and `database` to specify a hierarchical location for table.

    Parameters
    ----------
    schema
        A schema for the table
    name
        Name for the table. One is generated if this value is `None`.
    catalog
        A collection of database.
    database
        A collection of tables. Required if catalog is not `None`.

    Returns
    -------
    Table
        A table expression

    Examples
    --------
    Create a table with no data backing it

    >>> import ibis
    >>> ibis.options.interactive = False
    >>> t = ibis.table(schema=dict(a="int", b="string"), name="t")
    >>> t
    UnboundTable: t
      a int64
      b string


    Create a table with no data backing it in a specific location

    >>> import ibis
    >>> ibis.options.interactive = False
    >>> t = ibis.table(schema=dict(a="int"), name="t", catalog="cat", database="db")
    >>> t
    UnboundTable: cat.db.t
      a int64
    """
    if name is None:
        if isinstance(schema, type):
            name = schema.__name__
        else:
            name = next(_table_names)
    if catalog is not None and database is None:
        raise ValueError(
            "A catalog-only namespace is invalid in Ibis, "
            "please specify a database as well."
        )

    return ops.UnboundTable(
        name=name,
        schema=schema,
        namespace=ops.Namespace(catalog=catalog, database=database),
    ).to_expr()


def memtable(
    data,
    *,
    columns: Iterable[str] | None = None,
    schema: SchemaLike | None = None,
    name: str | None = None,
) -> Table:
    """Construct an ibis table expression from in-memory data.

    Parameters
    ----------
    data
        A table-like object (`pandas.DataFrame`, `pyarrow.Table`, or
        `polars.DataFrame`), or any data accepted by the `pandas.DataFrame`
        constructor (e.g. a list of dicts).

        Note that ibis objects (e.g. `MapValue`) may not be passed in as part
        of `data` and will result in an error.

        Do not depend on the underlying storage type (e.g., pyarrow.Table),
        it's subject to change across non-major releases.
    columns
        Optional [](`typing.Iterable`) of [](`str`) column names. If provided,
        must match the number of columns in `data`.
    schema
        Optional [`Schema`](./schemas.qmd#ibis.expr.schema.Schema).
        The functions use `data` to infer a schema if not passed.
    name
        Optional name of the table.

    Returns
    -------
    Table
        A table expression backed by in-memory data.

    Examples
    --------
    >>> import ibis
    >>> t = ibis.memtable([{"a": 1}, {"a": 2}])
    >>> t
    InMemoryTable
      data:
        PandasDataFrameProxy:
             a
          0  1
          1  2

    >>> t = ibis.memtable([{"a": 1, "b": "foo"}, {"a": 2, "b": "baz"}])
    >>> t
    InMemoryTable
      data:
        PandasDataFrameProxy:
             a    b
          0  1  foo
          1  2  baz

    Create a table literal without column names embedded in the data and pass
    `columns`

    >>> t = ibis.memtable([(1, "foo"), (2, "baz")], columns=["a", "b"])
    >>> t
    InMemoryTable
      data:
        PandasDataFrameProxy:
             a    b
          0  1  foo
          1  2  baz

    Create a table literal without column names embedded in the data. Ibis
    generates column names if none are provided.

    >>> t = ibis.memtable([(1, "foo"), (2, "baz")])
    >>> t
    InMemoryTable
      data:
        PandasDataFrameProxy:
             col0 col1
          0     1  foo
          1     2  baz

    """
    if columns is not None and schema is not None:
        raise NotImplementedError(
            "passing `columns` and schema` is ambiguous; "
            "pass one or the other but not both"
        )
    return _memtable(data, name=name, schema=schema, columns=columns)


@lazy_singledispatch
def _memtable(
    data: pd.DataFrame | Any,
    *,
    columns: Iterable[str] | None = None,
    schema: SchemaLike | None = None,
    name: str | None = None,
) -> Table:
    import pandas as pd

    from xorq.vendor.ibis.formats.pandas import PandasDataFrameProxy

    if not isinstance(data, pd.DataFrame):
        df = pd.DataFrame(data, columns=columns)
    else:
        df = data

    if df.columns.inferred_type != "string":
        cols = df.columns
        newcols = getattr(
            schema,
            "names",
            (f"col{i:d}" for i in builtins.range(len(cols))),
        )
        df = df.rename(columns=dict(zip(cols, newcols)))

    if columns is not None:
        if (provided_col := len(columns)) != (exist_col := len(df.columns)):
            raise ValueError(
                "Provided `columns` must have an entry for each column in `data`.\n"
                f"`columns` has {provided_col} elements but `data` has {exist_col} columns."
            )

        df = df.rename(columns=dict(zip(df.columns, columns)))

    # verify that the DataFrame has no duplicate column names because ibis
    # doesn't allow that
    cols = df.columns
    dupes = [name for name, count in Counter(cols).items() if count > 1]
    if dupes:
        raise XorqInputError(
            f"Duplicate column names found in DataFrame when constructing memtable: {dupes}"
        )

    op = ops.InMemoryTable(
        name=name if name is not None else util.gen_name("pandas_memtable"),
        schema=sch.infer(df) if schema is None else schema,
        data=PandasDataFrameProxy(df),
    )
    return op.to_expr()


@_memtable.register("pyarrow.Table")
def _memtable_from_pyarrow_table(
    data: pa.Table,
    *,
    name: str | None = None,
    schema: SchemaLike | None = None,
    columns: Iterable[str] | None = None,
):
    from xorq.vendor.ibis.formats.pyarrow import PyArrowTableProxy

    if columns is not None:
        assert schema is None, "if `columns` is not `None` then `schema` must be `None`"
        schema = sch.Schema(dict(zip(columns, sch.infer(data).values())))
    return ops.InMemoryTable(
        name=name if name is not None else util.gen_name("pyarrow_memtable"),
        schema=sch.infer(data) if schema is None else schema,
        data=PyArrowTableProxy(data),
    ).to_expr()


@_memtable.register("polars.LazyFrame")
def _memtable_from_polars_lazyframe(data: pl.LazyFrame, **kwargs):
    return _memtable_from_polars_dataframe(data.collect(), **kwargs)


@_memtable.register("polars.DataFrame")
def _memtable_from_polars_dataframe(
    data: pl.DataFrame,
    *,
    name: str | None = None,
    schema: SchemaLike | None = None,
    columns: Iterable[str] | None = None,
):
    from xorq.vendor.ibis.formats.polars import PolarsDataFrameProxy

    if columns is not None:
        assert schema is None, "if `columns` is not `None` then `schema` must be `None`"
        schema = sch.Schema(dict(zip(columns, sch.infer(data).values())))
    return ops.InMemoryTable(
        name=name if name is not None else util.gen_name("polars_memtable"),
        schema=sch.infer(data) if schema is None else schema,
        data=PolarsDataFrameProxy(data),
    ).to_expr()


def _deferred_method_call(expr, method_name, **kwargs):
    method = operator.methodcaller(method_name, **kwargs)
    if isinstance(expr, str):
        value = _[expr]
    elif isinstance(expr, Deferred):
        value = expr
    elif callable(expr):
        value = expr(_)
    else:
        value = expr
    return method(value)


def desc(expr: ir.Column | str, nulls_first: bool = False) -> ir.Value:
    """Create a descending sort key from `expr` or column name.

    Parameters
    ----------
    expr
        The expression or column name to use for sorting
    nulls_first
        Bool to indicate weather to put NULL values first or not.

    See Also
    --------
    [`Value.desc()`](./expression-generic.qmd#ibis.expr.types.generic.Value.desc)

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.examples.penguins.fetch()
    >>> t[["species", "year"]].order_by(ibis.desc("year")).head()
    ┏━━━━━━━━━┳━━━━━━━┓
    ┃ species ┃ year  ┃
    ┡━━━━━━━━━╇━━━━━━━┩
    │ string  │ int64 │
    ├─────────┼───────┤
    │ Adelie  │  2009 │
    │ Adelie  │  2009 │
    │ Adelie  │  2009 │
    │ Adelie  │  2009 │
    │ Adelie  │  2009 │
    └─────────┴───────┘

    Returns
    -------
    ir.ValueExpr
        An expression

    """
    return _deferred_method_call(expr, "desc", nulls_first=nulls_first)


def asc(expr: ir.Column | str, nulls_first: bool = False) -> ir.Value:
    """Create a ascending sort key from `asc` or column name.

    Parameters
    ----------
    expr
        The expression or column name to use for sorting
    nulls_first
        Bool to indicate weather to put NULL values first or not.

    See Also
    --------
    [`Value.asc()`](./expression-generic.qmd#ibis.expr.types.generic.Value.asc)

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.examples.penguins.fetch()
    >>> t[["species", "year"]].order_by(ibis.asc("year")).head()
    ┏━━━━━━━━━┳━━━━━━━┓
    ┃ species ┃ year  ┃
    ┡━━━━━━━━━╇━━━━━━━┩
    │ string  │ int64 │
    ├─────────┼───────┤
    │ Adelie  │  2007 │
    │ Adelie  │  2007 │
    │ Adelie  │  2007 │
    │ Adelie  │  2007 │
    │ Adelie  │  2007 │
    └─────────┴───────┘

    Returns
    -------
    ir.ValueExpr
        An expression

    """
    return _deferred_method_call(expr, "asc", nulls_first=nulls_first)


def preceding(value) -> ir.Value:
    return ops.WindowBoundary(value, preceding=True).to_expr()


def following(value) -> ir.Value:
    return ops.WindowBoundary(value, preceding=False).to_expr()


def and_(*predicates: ir.BooleanValue) -> ir.BooleanValue:
    """Combine multiple predicates using `&`.

    Parameters
    ----------
    predicates
        Boolean value expressions

    Returns
    -------
    BooleanValue
        A new predicate that evaluates to True if all composing predicates are
        True. If no predicates were provided, returns True.

    """
    if not predicates:
        return literal(True)
    return functools.reduce(operator.and_, predicates)


def or_(*predicates: ir.BooleanValue) -> ir.BooleanValue:
    """Combine multiple predicates using `|`.

    Parameters
    ----------
    predicates
        Boolean value expressions

    Returns
    -------
    BooleanValue
        A new predicate that evaluates to True if any composing predicates are
        True. If no predicates were provided, returns False.

    """
    if not predicates:
        return literal(False)
    return functools.reduce(operator.or_, predicates)


def random() -> ir.FloatingScalar:
    """Return a random floating point number in the range [0.0, 1.0).

    Similar to [](`random.random`) in the Python standard library.

    ::: {.callout-note}
    ## Repeated use of `random`

    `ibis.random()` will generate a column of distinct random numbers even if
    the same instance of `ibis.random()` is reused.

    When Ibis compiles an expression to SQL, each place where `random` is used
    will render as a separate call to the given backend's random number
    generator.

    ```python
    >>> from xorq.vendor.ibis.interactive import *
    >>> t = ibis.memtable({"a": range(5)})
    >>> r_a = ibis.random()
    >>> t.mutate(random_1=r_a, random_2=r_a)  # doctest: +SKIP
    ┏━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┓
    ┃ a     ┃ random_1 ┃ random_2 ┃
    ┡━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━┩
    │ int64 │ float64  │ float64  │
    ├───────┼──────────┼──────────┤
    │     0 │ 0.191130 │ 0.098715 │
    │     1 │ 0.255262 │ 0.828454 │
    │     2 │ 0.011804 │ 0.392275 │
    │     3 │ 0.309941 │ 0.347300 │
    │     4 │ 0.482783 │ 0.095562 │
    └───────┴──────────┴──────────┘
    ```
    :::

    Returns
    -------
    FloatingScalar
        Random float value expression

    """
    return ops.RandomScalar().to_expr()


def uuid() -> ir.UUIDScalar:
    """Return a random UUID version 4 value.

    Similar to [('uuid.uuid4`) in the Python standard library.

    Examples
    --------
    >>> from xorq.vendor.ibis.interactive import *
    >>> ibis.uuid()  # doctest: +SKIP
    UUID('e57e927b-aed2-483b-9140-dc32a26cad95')

    Returns
    -------
    UUIDScalar
        Random UUID value expression
    """
    return ops.RandomUUID().to_expr()


@overload
def timestamp(
    value_or_year: int | ir.IntegerValue | Deferred,
    month: int | ir.IntegerValue | Deferred,
    day: int | ir.IntegerValue | Deferred,
    hour: int | ir.IntegerValue | Deferred,
    minute: int | ir.IntegerValue | Deferred,
    second: int | ir.IntegerValue | Deferred,
    /,
    timezone: str | None = None,
) -> TimestampValue: ...


@overload
def timestamp(value_or_year: Any, /, timezone: str | None = None) -> TimestampValue: ...


@deferrable
def timestamp(
    value_or_year,
    month=None,
    day=None,
    hour=None,
    minute=None,
    second=None,
    /,
    timezone=None,
):
    """Construct a timestamp scalar or column.

    Parameters
    ----------
    value_or_year
        Either a string value or `datetime.datetime` to coerce to a timestamp,
        or an integral value representing the timestamp year component.
    month
        The timestamp month component; required if `value_or_year` is a year.
    day
        The timestamp day component; required if `value_or_year` is a year.
    hour
        The timestamp hour component; required if `value_or_year` is a year.
    minute
        The timestamp minute component; required if `value_or_year` is a year.
    second
        The timestamp second component; required if `value_or_year` is a year.
    timezone
        The timezone name, or none for a timezone-naive timestamp.

    Returns
    -------
    TimestampValue
        A timestamp expression

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True

    Create a timestamp scalar from a string

    >>> ibis.timestamp("2023-01-02T03:04:05")
    ┌─────────────────────┐
    │ 2023-01-02 03:04:05 │
    └─────────────────────┘

    Create a timestamp scalar from components

    >>> ibis.timestamp(2023, 1, 2, 3, 4, 5)
    ┌─────────────────────┐
    │ 2023-01-02 03:04:05 │
    └─────────────────────┘

    Create a timestamp column from components

    >>> t = ibis.memtable({"y": [2001, 2002], "m": [1, 4], "d": [2, 5], "h": [3, 6]})
    >>> ibis.timestamp(t.y, t.m, t.d, t.h, 0, 0).name("timestamp")
    ┏━━━━━━━━━━━━━━━━━━━━━┓
    ┃ timestamp           ┃
    ┡━━━━━━━━━━━━━━━━━━━━━┩
    │ timestamp           │
    ├─────────────────────┤
    │ 2001-01-02 03:00:00 │
    │ 2002-04-05 06:00:00 │
    └─────────────────────┘

    """
    args = (value_or_year, month, day, hour, minute, second)
    is_ymdhms = any(a is not None for a in args[1:])

    if is_ymdhms:
        if timezone is not None:
            raise NotImplementedError(
                "Timezone currently not supported when creating a timestamp from components"
            )
        return ops.TimestampFromYMDHMS(*args).to_expr()
    elif isinstance(value_or_year, (numbers.Real, ir.IntegerValue)):
        raise TypeError("Use ibis.literal(...).as_timestamp() instead")
    elif isinstance(value_or_year, ir.Expr):
        return value_or_year.cast(dt.Timestamp(timezone=timezone))
    else:
        value = normalize_datetime(value_or_year)
        tzinfo = normalize_timezone(timezone or value.tzinfo)
        timezone = tzinfo.tzname(value) if tzinfo is not None else None
        return literal(value, type=dt.Timestamp(timezone=timezone))


@overload
def date(
    value_or_year: int | ir.IntegerValue | Deferred,
    month: int | ir.IntegerValue | Deferred,
    day: int | ir.IntegerValue | Deferred,
    /,
) -> DateValue: ...


@overload
def date(value_or_year: Any, /) -> DateValue: ...


@deferrable
def date(value_or_year, month=None, day=None, /):
    """Construct a date scalar or column.

    Parameters
    ----------
    value_or_year
        Either a string value or `datetime.date` to coerce to a date, or
        an integral value representing the date year component.
    month
        The date month component; required if `value_or_year` is a year.
    day
        The date day component; required if `value_or_year` is a year.

    Returns
    -------
    DateValue
        A date expression

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True

    Create a date scalar from a string

    >>> ibis.date("2023-01-02")
    ┌────────────┐
    │ 2023-01-02 │
    └────────────┘

    Create a date scalar from year, month, and day

    >>> ibis.date(2023, 1, 2)
    ┌────────────┐
    │ 2023-01-02 │
    └────────────┘

    Create a date column from year, month, and day

    >>> t = ibis.memtable(dict(year=[2001, 2002], month=[1, 3], day=[2, 4]))
    >>> ibis.date(t.year, t.month, t.day).name("my_date")
    ┏━━━━━━━━━━━━┓
    ┃ my_date    ┃
    ┡━━━━━━━━━━━━┩
    │ date       │
    ├────────────┤
    │ 2001-01-02 │
    │ 2002-03-04 │
    └────────────┘

    """
    if month is not None or day is not None:
        return ops.DateFromYMD(value_or_year, month, day).to_expr()
    elif isinstance(value_or_year, ir.Expr):
        return value_or_year.cast(dt.date)
    else:
        return literal(value_or_year, type=dt.date)


@overload
def time(
    value_or_hour: int | ir.IntegerValue | Deferred,
    minute: int | ir.IntegerValue | Deferred,
    second: int | ir.IntegerValue | Deferred,
    /,
) -> TimeValue: ...


@overload
def time(value_or_hour: Any, /) -> TimeValue: ...


@deferrable
def time(value_or_hour, minute=None, second=None, /):
    """Return a time literal if `value` is coercible to a time.

    Parameters
    ----------
    value_or_hour
        Either a string value or `datetime.time` to coerce to a time, or
        an integral value representing the time hour component.
    minute
        The time minute component; required if `value_or_hour` is an hour.
    second
        The time second component; required if `value_or_hour` is an hour.

    Returns
    -------
    TimeValue
        A time expression

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True

    Create a time scalar from a string

    >>> ibis.time("01:02:03")
    ┌──────────┐
    │ 01:02:03 │
    └──────────┘

    Create a time scalar from hour, minute, and second

    >>> ibis.time(1, 2, 3)
    ┌──────────┐
    │ 01:02:03 │
    └──────────┘

    Create a time column from hour, minute, and second

    >>> t = ibis.memtable({"h": [1, 4], "m": [2, 5], "s": [3, 6]})
    >>> ibis.time(t.h, t.m, t.s).name("time")
    ┏━━━━━━━━━━┓
    ┃ time     ┃
    ┡━━━━━━━━━━┩
    │ time     │
    ├──────────┤
    │ 01:02:03 │
    │ 04:05:06 │
    └──────────┘

    """
    if minute is not None or second is not None:
        return ops.TimeFromHMS(value_or_hour, minute, second).to_expr()
    elif isinstance(value_or_hour, ir.Expr):
        return value_or_hour.cast(dt.time)
    else:
        return literal(value_or_hour, type=dt.time)


def interval(
    value: int | datetime.timedelta | None = None,
    unit: str = "s",
    *,
    years: int | None = None,
    quarters: int | None = None,
    months: int | None = None,
    weeks: int | None = None,
    days: int | None = None,
    hours: int | None = None,
    minutes: int | None = None,
    seconds: int | None = None,
    milliseconds: int | None = None,
    microseconds: int | None = None,
    nanoseconds: int | None = None,
) -> ir.IntervalScalar:
    """Return an interval literal expression.

    Parameters
    ----------
    value
        Interval value.
    unit
        Unit of `value`
    years
        Number of years
    quarters
        Number of quarters
    months
        Number of months
    weeks
        Number of weeks
    days
        Number of days
    hours
        Number of hours
    minutes
        Number of minutes
    seconds
        Number of seconds
    milliseconds
        Number of milliseconds
    microseconds
        Number of microseconds
    nanoseconds
        Number of nanoseconds

    Returns
    -------
    IntervalScalar
        An interval expression

    """
    keyword_value_unit = [
        ("nanoseconds", nanoseconds, "ns"),
        ("microseconds", microseconds, "us"),
        ("milliseconds", milliseconds, "ms"),
        ("seconds", seconds, "s"),
        ("minutes", minutes, "m"),
        ("hours", hours, "h"),
        ("days", days, "D"),
        ("weeks", weeks, "W"),
        ("months", months, "M"),
        ("quarters", quarters, "Q"),
        ("years", years, "Y"),
    ]
    if value is not None:
        for kw, v, _abbrev in keyword_value_unit:
            if v is not None:
                raise TypeError(f"Cannot provide both 'value' and '{kw}'")
        if isinstance(value, datetime.timedelta):
            components = [
                (value.microseconds, "us"),
                (value.seconds, "s"),
                (value.days, "D"),
            ]
            components = [(v, u) for v, u in components if v]
        elif isinstance(value, int):
            components = [(value, unit)]
        else:
            raise TypeError("value must be an integer or timedelta")
    else:
        components = [(v, u) for _, v, u in keyword_value_unit if v is not None]

    # If no components, default to 0 s
    if not components:
        components.append((0, "s"))

    intervals = [literal(v, type=dt.Interval(u)) for v, u in components]
    return functools.reduce(operator.add, intervals)


def case() -> bl.SearchedCaseBuilder:
    """Begin constructing a case expression.

    Use the `.when` method on the resulting object followed by `.end` to create a
    complete case expression.

    Returns
    -------
    SearchedCaseBuilder
        A builder object to use for constructing a case expression.

    See Also
    --------
    [`Value.case()`](./expression-generic.qmd#ibis.expr.types.generic.Value.case)

    Examples
    --------
    >>> import ibis
    >>> from ibis import _
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable(
    ...     {
    ...         "left": [1, 2, 3, 4],
    ...         "symbol": ["+", "-", "*", "/"],
    ...         "right": [5, 6, 7, 8],
    ...     }
    ... )
    >>> t.mutate(
    ...     result=(
    ...         ibis.case()
    ...         .when(_.symbol == "+", _.left + _.right)
    ...         .when(_.symbol == "-", _.left - _.right)
    ...         .when(_.symbol == "*", _.left * _.right)
    ...         .when(_.symbol == "/", _.left / _.right)
    ...         .end()
    ...     )
    ... )
    ┏━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━━┓
    ┃ left  ┃ symbol ┃ right ┃ result  ┃
    ┡━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━━┩
    │ int64 │ string │ int64 │ float64 │
    ├───────┼────────┼───────┼─────────┤
    │     1 │ +      │     5 │     6.0 │
    │     2 │ -      │     6 │    -4.0 │
    │     3 │ *      │     7 │    21.0 │
    │     4 │ /      │     8 │     0.5 │
    └───────┴────────┴───────┴─────────┘

    """
    return bl.SearchedCaseBuilder()


def now() -> ir.TimestampScalar:
    """Return an expression that will compute the current timestamp.

    Returns
    -------
    TimestampScalar
        An expression representing the current timestamp.

    """
    return ops.TimestampNow().to_expr()


def today() -> ir.DateScalar:
    """Return an expression that will compute the current date.

    Returns
    -------
    DateScalar
        An expression representing the current date.

    """
    return ops.DateNow().to_expr()


def rank() -> ir.IntegerColumn:
    """Compute position of first element within each equal-value group in sorted order.

    Equivalent to SQL's `RANK()` window function.

    Returns
    -------
    Int64Column
        The min rank

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable({"values": [1, 2, 1, 2, 3, 2]})
    >>> t.mutate(rank=ibis.rank().over(order_by=t.values))
    ┏━━━━━━━━┳━━━━━━━┓
    ┃ values ┃ rank  ┃
    ┡━━━━━━━━╇━━━━━━━┩
    │ int64  │ int64 │
    ├────────┼───────┤
    │      1 │     0 │
    │      1 │     0 │
    │      2 │     2 │
    │      2 │     2 │
    │      2 │     2 │
    │      3 │     5 │
    └────────┴───────┘

    """
    return ops.MinRank().to_expr()


def dense_rank() -> ir.IntegerColumn:
    """Position of first element within each group of equal values.

    Values are returned in sorted order and duplicate values are ignored.

    Equivalent to SQL's `DENSE_RANK()`.

    Returns
    -------
    IntegerColumn
        The rank

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable({"values": [1, 2, 1, 2, 3, 2]})
    >>> t.mutate(rank=ibis.dense_rank().over(order_by=t.values))
    ┏━━━━━━━━┳━━━━━━━┓
    ┃ values ┃ rank  ┃
    ┡━━━━━━━━╇━━━━━━━┩
    │ int64  │ int64 │
    ├────────┼───────┤
    │      1 │     0 │
    │      1 │     0 │
    │      2 │     1 │
    │      2 │     1 │
    │      2 │     1 │
    │      3 │     2 │
    └────────┴───────┘

    """
    return ops.DenseRank().to_expr()


def percent_rank() -> ir.FloatingColumn:
    """Return the relative rank of the values in the column.

    Returns
    -------
    FloatingColumn
        The percent rank

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable({"values": [1, 2, 1, 2, 3, 2]})
    >>> t.mutate(pct_rank=ibis.percent_rank().over(order_by=t.values))
    ┏━━━━━━━━┳━━━━━━━━━━┓
    ┃ values ┃ pct_rank ┃
    ┡━━━━━━━━╇━━━━━━━━━━┩
    │ int64  │ float64  │
    ├────────┼──────────┤
    │      1 │      0.0 │
    │      1 │      0.0 │
    │      2 │      0.4 │
    │      2 │      0.4 │
    │      2 │      0.4 │
    │      3 │      1.0 │
    └────────┴──────────┘

    """
    return ops.PercentRank().to_expr()


def cume_dist() -> ir.FloatingColumn:
    """Return the cumulative distribution over a window.

    Returns
    -------
    FloatingColumn
        The cumulative distribution

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable({"values": [1, 2, 1, 2, 3, 2]})
    >>> t.mutate(dist=ibis.cume_dist().over(order_by=t.values))
    ┏━━━━━━━━┳━━━━━━━━━━┓
    ┃ values ┃ dist     ┃
    ┡━━━━━━━━╇━━━━━━━━━━┩
    │ int64  │ float64  │
    ├────────┼──────────┤
    │      1 │ 0.333333 │
    │      1 │ 0.333333 │
    │      2 │ 0.833333 │
    │      2 │ 0.833333 │
    │      2 │ 0.833333 │
    │      3 │ 1.000000 │
    └────────┴──────────┘

    """
    return ops.CumeDist().to_expr()


def ntile(buckets: int | ir.IntegerValue) -> ir.IntegerColumn:
    """Return the integer number of a partitioning of the column values.

    Parameters
    ----------
    buckets
        Number of buckets to partition into

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable({"values": [1, 2, 1, 2, 3, 2]})
    >>> t.mutate(ntile=ibis.ntile(2).over(order_by=t.values))
    ┏━━━━━━━━┳━━━━━━━┓
    ┃ values ┃ ntile ┃
    ┡━━━━━━━━╇━━━━━━━┩
    │ int64  │ int64 │
    ├────────┼───────┤
    │      1 │     0 │
    │      1 │     0 │
    │      2 │     0 │
    │      2 │     1 │
    │      2 │     1 │
    │      3 │     1 │
    └────────┴───────┘

    """
    return ops.NTile(buckets).to_expr()


def row_number() -> ir.IntegerColumn:
    """Return an analytic function expression for the current row number.

    ::: {.callout-note}
    `row_number` is normalized across backends to start at 0
    :::

    Returns
    -------
    IntegerColumn
        A column expression enumerating rows

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable({"values": [1, 2, 1, 2, 3, 2]})
    >>> t.mutate(rownum=ibis.row_number())
    ┏━━━━━━━━┳━━━━━━━━┓
    ┃ values ┃ rownum ┃
    ┡━━━━━━━━╇━━━━━━━━┩
    │ int64  │ int64  │
    ├────────┼────────┤
    │      1 │      0 │
    │      2 │      1 │
    │      1 │      2 │
    │      2 │      3 │
    │      3 │      4 │
    │      2 │      5 │
    └────────┴────────┘

    """
    return ops.RowNumber().to_expr()


def read_csv(
    sources: str | Path | Sequence[str | Path],
    table_name: str | None = None,
    **kwargs: Any,
) -> ir.Table:
    """Lazily load a CSV or set of CSVs.

    This function delegates to the `read_csv` method on the current default
    backend (DuckDB or `ibis.config.default_backend`).

    Parameters
    ----------
    sources
        A filesystem path or URL or list of same.  Supports CSV and TSV files.
    table_name
        A name to refer to the table.  If not provided, a name will be generated.
    kwargs
        Backend-specific keyword arguments for the file type. For the DuckDB
        backend used by default, please refer to:

        * CSV/TSV: https://duckdb.org/docs/data/csv/overview.html#parameters.

    Returns
    -------
    ir.Table
        Table expression representing a file

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> lines = '''a,b
    ... 1,d
    ... 2,
    ... ,f
    ... '''
    >>> with open("/tmp/lines.csv", mode="w") as f:
    ...     nbytes = f.write(lines)  # nbytes is unused
    >>> t = ibis.read_csv("/tmp/lines.csv")
    >>> t
    ┏━━━━━━━┳━━━━━━━━┓
    ┃ a     ┃ b      ┃
    ┡━━━━━━━╇━━━━━━━━┩
    │ int64 │ string │
    ├───────┼────────┤
    │     1 │ d      │
    │     2 │ NULL   │
    │  NULL │ f      │
    └───────┴────────┘

    """
    from xorq.vendor.ibis.config import _default_backend

    con = _default_backend()
    return con.read_csv(sources, table_name=table_name, **kwargs)


@experimental
def read_json(
    sources: str | Path | Sequence[str | Path],
    table_name: str | None = None,
    **kwargs: Any,
) -> ir.Table:
    """Lazily load newline-delimited JSON data.

    This function delegates to the `read_json` method on the current default
    backend (DuckDB or `ibis.config.default_backend`).

    Parameters
    ----------
    sources
        A filesystem path or URL or list of same.
    table_name
        A name to refer to the table.  If not provided, a name will be generated.
    kwargs
        Backend-specific keyword arguments for the file type. See
        https://duckdb.org/docs/extensions/json.html for details.

    Returns
    -------
    ir.Table
        Table expression representing a file

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> lines = '''
    ... {"a": 1, "b": "d"}
    ... {"a": 2, "b": null}
    ... {"a": null, "b": "f"}
    ... '''
    >>> with open("/tmp/lines.json", mode="w") as f:
    ...     nbytes = f.write(lines)  # nbytes is unused
    >>> t = ibis.read_json("/tmp/lines.json")
    >>> t
    ┏━━━━━━━┳━━━━━━━━┓
    ┃ a     ┃ b      ┃
    ┡━━━━━━━╇━━━━━━━━┩
    │ int64 │ string │
    ├───────┼────────┤
    │     1 │ d      │
    │     2 │ NULL   │
    │  NULL │ f      │
    └───────┴────────┘

    """
    from xorq.vendor.ibis.config import _default_backend

    con = _default_backend()
    return con.read_json(sources, table_name=table_name, **kwargs)


def read_parquet(
    sources: str | Path | Sequence[str | Path],
    table_name: str | None = None,
    **kwargs: Any,
) -> ir.Table:
    """Lazily load a parquet file or set of parquet files.

    This function delegates to the `read_parquet` method on the current default
    backend (DuckDB or `ibis.config.default_backend`).

    Parameters
    ----------
    sources
        A filesystem path or URL or list of same.
    table_name
        A name to refer to the table.  If not provided, a name will be generated.
    kwargs
        Backend-specific keyword arguments for the file type. For the DuckDB
        backend used by default, please refer to:

        * Parquet: https://duckdb.org/docs/data/parquet

    Returns
    -------
    ir.Table
        Table expression representing a file

    Examples
    --------
    >>> import ibis
    >>> import pandas as pd
    >>> ibis.options.interactive = True
    >>> df = pd.DataFrame({"a": [1, 2, 3], "b": list("ghi")})
    >>> df
       a  b
    0  1  g
    1  2  h
    2  3  i
    >>> df.to_parquet("/tmp/data.parquet")
    >>> t = ibis.read_parquet("/tmp/data.parquet")
    >>> t
    ┏━━━━━━━┳━━━━━━━━┓
    ┃ a     ┃ b      ┃
    ┡━━━━━━━╇━━━━━━━━┩
    │ int64 │ string │
    ├───────┼────────┤
    │     1 │ g      │
    │     2 │ h      │
    │     3 │ i      │
    └───────┴────────┘

    """
    from xorq.vendor.ibis.config import _default_backend

    con = _default_backend()
    return con.read_parquet(sources, table_name=table_name, **kwargs)


def read_delta(
    source: str | Path, table_name: str | None = None, **kwargs: Any
) -> ir.Table:
    """Lazily load a Delta Lake table.

    Parameters
    ----------
    source
        A filesystem path or URL.
    table_name
        A name to refer to the table.  If not provided, a name will be generated.
    kwargs
        Backend-specific keyword arguments for the file type.

    Returns
    -------
    ir.Table
        Table expression representing a file

    Examples
    --------
    >>> import ibis
    >>> import pandas as pd
    >>> ibis.options.interactive = True
    >>> df = pd.DataFrame({"a": [1, 2, 3], "b": list("ghi")})
    >>> df
       a  b
    0  1  g
    1  2  h
    2  3  i
    >>> import deltalake as dl
    >>> dl.write_deltalake("/tmp/data.delta", df, mode="overwrite")
    >>> t = ibis.read_delta("/tmp/data.delta")
    >>> t
    ┏━━━━━━━┳━━━━━━━━┓
    ┃ a     ┃ b      ┃
    ┡━━━━━━━╇━━━━━━━━┩
    │ int64 │ string │
    ├───────┼────────┤
    │     1 │ g      │
    │     2 │ h      │
    │     3 │ i      │
    └───────┴────────┘

    """
    from xorq.vendor.ibis.config import _default_backend

    con = _default_backend()
    return con.read_delta(source, table_name=table_name, **kwargs)


def set_backend(backend: str | BaseBackend) -> None:
    """Set the default Ibis backend.

    Parameters
    ----------
    backend
        May be a backend name or URL, or an existing backend instance.

    Examples
    --------
    You can pass the backend as a name:

    >>> import ibis
    >>> ibis.set_backend("polars")

    Or as a URI

    >>> ibis.set_backend(
    ...     "postgres://user:password@hostname:5432"
    ... )  # quartodoc: +SKIP # doctest: +SKIP

    Or as an existing backend instance

    >>> ibis.set_backend(ibis.duckdb.connect())

    """
    from xorq.vendor import ibis

    if isinstance(backend, str) and backend.isidentifier():
        try:
            backend_type = getattr(ibis, backend)
        except AttributeError:
            pass
        else:
            backend = backend_type.connect()
    if isinstance(backend, str):
        backend = ibis.connect(backend)

    ibis.options.default_backend = backend


def get_backend(expr: Expr | None = None) -> BaseBackend:
    """Get the current Ibis backend to use for a given expression.

    expr
        An expression to get the backend from. If not passed, the default
        backend is returned.

    Returns
    -------
    BaseBackend
        The Ibis backend.

    """
    if expr is None:
        from xorq.vendor.ibis.config import _default_backend

        return _default_backend()
    return expr._find_backend(use_default=True)


def window(
    preceding=None,
    following=None,
    order_by=None,
    group_by=None,
    *,
    rows=None,
    range=None,
    between=None,
):
    """Create a window clause for use with window functions.

    The `ROWS` window clause includes peer rows based on differences in row
    **number** whereas `RANGE` includes rows based on the differences in row
    **value** of a single `order_by` expression.

    All window frame bounds are inclusive.

    Parameters
    ----------
    preceding
        Number of preceding rows in the window
    following
        Number of following rows in the window
    group_by
        Grouping key
    order_by
        Ordering key
    rows
        Whether to use the `ROWS` window clause
    range
        Whether to use the `RANGE` window clause
    between
        Automatically infer the window kind based on the boundaries

    Returns
    -------
    Window
        A window frame

    """
    has_rows = rows is not None
    has_range = range is not None
    has_between = between is not None
    has_preceding_following = preceding is not None or following is not None
    if has_rows + has_range + has_between + has_preceding_following > 1:
        raise XorqInputError(
            "Must only specify either `rows`, `range`, `between` or `preceding`/`following`"
        )

    builder = bl.LegacyWindowBuilder().group_by(group_by).order_by(order_by)
    if has_rows:
        return builder.rows(*rows)
    elif has_range:
        return builder.range(*range)
    elif has_between:
        return builder.between(*between)
    elif has_preceding_following:
        return builder.preceding_following(preceding, following)
    else:
        return builder


def rows_window(preceding=None, following=None, group_by=None, order_by=None):
    """Create a rows-based window clause for use with window functions.

    This ROWS window clause aggregates rows based upon differences in row
    number.

    All window frames / ranges are inclusive.

    Parameters
    ----------
    preceding
        Number of preceding rows in the window
    following
        Number of following rows in the window
    group_by
        Grouping key
    order_by
        Ordering key

    Returns
    -------
    Window
        A window frame

    """
    return (
        bl.LegacyWindowBuilder()
        .group_by(group_by)
        .order_by(order_by)
        .preceding_following(preceding, following, how="rows")
    )


def range_window(preceding=None, following=None, group_by=None, order_by=None):
    """Create a range-based window clause for use with window functions.

    This RANGE window clause aggregates rows based upon differences in the
    value of the order-by expression.

    All window frames / ranges are inclusive.

    Parameters
    ----------
    preceding
        Number of preceding rows in the window
    following
        Number of following rows in the window
    group_by
        Grouping key
    order_by
        Ordering key

    Returns
    -------
    Window
        A window frame

    """
    return (
        bl.LegacyWindowBuilder()
        .group_by(group_by)
        .order_by(order_by)
        .preceding_following(preceding, following, how="range")
    )


def cumulative_window(group_by=None, order_by=None):
    """Create a cumulative window for use with window functions.

    All window frames / ranges are inclusive.

    Parameters
    ----------
    group_by
        Grouping key
    order_by
        Ordering key

    Returns
    -------
    Window
        A window frame

    """
    return window(rows=(None, 0), group_by=group_by, order_by=order_by)


def trailing_window(preceding, group_by=None, order_by=None):
    """Create a trailing window for use with window functions.

    Parameters
    ----------
    preceding
        The number of preceding rows
    group_by
        Grouping key
    order_by
        Ordering key

    Returns
    -------
    Window
        A window frame

    """
    return window(
        preceding=preceding, following=0, group_by=group_by, order_by=order_by
    )


def trailing_rows_window(preceding, group_by=None, order_by=None):
    """Create a trailing window for use with aggregate window functions.

    Parameters
    ----------
    preceding
        The number of preceding rows
    group_by
        Grouping key
    order_by
        Ordering key

    Returns
    -------
    Window
        A window frame

    """
    return rows_window(
        preceding=preceding, following=0, group_by=group_by, order_by=order_by
    )


def trailing_range_window(preceding, order_by, group_by=None):
    """Create a trailing range window for use with window functions.

    Parameters
    ----------
    preceding
        A value expression
    order_by
        Ordering key
    group_by
        Grouping key

    Returns
    -------
    Window
        A window frame

    """
    return range_window(
        preceding=preceding, following=0, group_by=group_by, order_by=order_by
    )


def union(table: ir.Table, *rest: ir.Table, distinct: bool = False) -> ir.Table:
    """Compute the set union of multiple table expressions.

    The input tables must have identical schemas.

    Parameters
    ----------
    table
        A table expression
    *rest
        Additional table expressions
    distinct
        Only return distinct rows

    Returns
    -------
    Table
        A new table containing the union of all input tables.

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t1 = ibis.memtable({"a": [1, 2]})
    >>> t1
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     1 │
    │     2 │
    └───────┘
    >>> t2 = ibis.memtable({"a": [2, 3]})
    >>> t2
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     2 │
    │     3 │
    └───────┘
    >>> ibis.union(t1, t2)  # union all by default
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     1 │
    │     2 │
    │     2 │
    │     3 │
    └───────┘
    >>> ibis.union(t1, t2, distinct=True).order_by("a")
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     1 │
    │     2 │
    │     3 │
    └───────┘

    """
    return table.union(*rest, distinct=distinct) if rest else table


def intersect(table: ir.Table, *rest: ir.Table, distinct: bool = True) -> ir.Table:
    """Compute the set intersection of multiple table expressions.

    The input tables must have identical schemas.

    Parameters
    ----------
    table
        A table expression
    *rest
        Additional table expressions
    distinct
        Only return distinct rows

    Returns
    -------
    Table
        A new table containing the intersection of all input tables.

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t1 = ibis.memtable({"a": [1, 2]})
    >>> t1
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     1 │
    │     2 │
    └───────┘
    >>> t2 = ibis.memtable({"a": [2, 3]})
    >>> t2
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     2 │
    │     3 │
    └───────┘
    >>> ibis.intersect(t1, t2)
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     2 │
    └───────┘

    """
    return table.intersect(*rest, distinct=distinct) if rest else table


def difference(table: ir.Table, *rest: ir.Table, distinct: bool = True) -> ir.Table:
    """Compute the set difference of multiple table expressions.

    The input tables must have identical schemas.

    Parameters
    ----------
    table
        A table expression
    *rest
        Additional table expressions
    distinct
        Only diff distinct rows not occurring in the calling table

    Returns
    -------
    Table
        The rows present in `self` that are not present in `tables`.

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t1 = ibis.memtable({"a": [1, 2]})
    >>> t1
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     1 │
    │     2 │
    └───────┘
    >>> t2 = ibis.memtable({"a": [2, 3]})
    >>> t2
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     2 │
    │     3 │
    └───────┘
    >>> ibis.difference(t1, t2)
    ┏━━━━━━━┓
    ┃ a     ┃
    ┡━━━━━━━┩
    │ int64 │
    ├───────┤
    │     1 │
    └───────┘

    """
    return table.difference(*rest, distinct=distinct) if rest else table


class Watermark(Concrete):
    time_col: str
    allowed_delay: ir.IntervalScalar


def watermark(time_col: str, allowed_delay: ir.IntervalScalar) -> Watermark:
    """Return a watermark object.

    Parameters
    ----------
    time_col
        The timestamp column that will be used to generate watermarks in event time processing.
    allowed_delay
        Length of time that events are allowed to be late.

    Returns
    -------
    Watermark
        A watermark object.

    """
    return Watermark(time_col=time_col, allowed_delay=allowed_delay)


@functools.singledispatch
def range(start, stop, step) -> ir.ArrayValue:
    """Generate a range of values.

    Integer ranges are supported, as well as timestamp ranges.

    ::: {.callout-note}
    `start` is inclusive and `stop` is exclusive, just like Python's builtin
    [](`range`).

    When `step` equals 0, however, this function will return an empty array.

    Python's `range` will raise an exception when `step` is zero.
    :::

    Parameters
    ----------
    start
        Lower bound of the range, inclusive.
    stop
        Upper bound of the range, exclusive.
    step
        Step value. Optional, defaults to 1.

    Returns
    -------
    ArrayValue
        An array of values

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True

    Range using only a stop argument

    >>> ibis.range(5)
    ┌────────────────┐
    │ [0, 1, ... +3] │
    └────────────────┘

    Simple range using start and stop

    >>> ibis.range(1, 5)
    ┌────────────────┐
    │ [1, 2, ... +2] │
    └────────────────┘

    Generate an empty range

    >>> ibis.range(0)
    ┌────┐
    │ [] │
    └────┘

    Negative step values are supported

    >>> ibis.range(10, 4, -2)
    ┌─────────────────┐
    │ [10, 8, ... +1] │
    └─────────────────┘

    `ibis.range` behaves the same as Python's range ...

    >>> ibis.range(0, 7, -1)
    ┌────┐
    │ [] │
    └────┘

    ... except when the step is zero, in which case `ibis.range` returns an
    empty array

    >>> ibis.range(0, 5, 0)
    ┌────┐
    │ [] │
    └────┘

    Because the resulting expression is array, you can unnest the values

    >>> ibis.range(5).unnest().name("numbers")
    ┏━━━━━━━━━┓
    ┃ numbers ┃
    ┡━━━━━━━━━┩
    │ int8    │
    ├─────────┤
    │       0 │
    │       1 │
    │       2 │
    │       3 │
    │       4 │
    └─────────┘

    Timestamp ranges are also supported

    >>> expr = ibis.range("2002-01-01", "2002-02-01", ibis.interval(days=2)).name("ts")
    >>> expr
    ┌──────────────────────────────────────────┐
    │ [                                        │
    │     datetime.datetime(2002, 1, 1, 0, 0), │
    │     datetime.datetime(2002, 1, 3, 0, 0), │
    │     ... +14                              │
    │ ]                                        │
    └──────────────────────────────────────────┘
    >>> expr.unnest()
    ┏━━━━━━━━━━━━━━━━━━━━━┓
    ┃ ts                  ┃
    ┡━━━━━━━━━━━━━━━━━━━━━┩
    │ timestamp           │
    ├─────────────────────┤
    │ 2002-01-01 00:00:00 │
    │ 2002-01-03 00:00:00 │
    │ 2002-01-05 00:00:00 │
    │ 2002-01-07 00:00:00 │
    │ 2002-01-09 00:00:00 │
    │ 2002-01-11 00:00:00 │
    │ 2002-01-13 00:00:00 │
    │ 2002-01-15 00:00:00 │
    │ 2002-01-17 00:00:00 │
    │ 2002-01-19 00:00:00 │
    │ …                   │
    └─────────────────────┘

    """
    raise NotImplementedError()


@range.register(int)
@range.register(ir.IntegerValue)
def _int_range(
    start: int,
    stop: int | ir.IntegerValue | None = None,
    step: int | ir.IntegerValue | None = None,
) -> ir.ArrayValue:
    if stop is None:
        stop = start
        start = 0
    if step is None:
        step = 1
    return ops.IntegerRange(start=start, stop=stop, step=step).to_expr()


@range.register(str)
@range.register(datetime.datetime)
@range.register(ir.TimestampValue)
def _timestamp_range(
    start: datetime.datetime | ir.TimestampValue | str,
    stop: datetime.datetime | ir.TimestampValue | str,
    step: datetime.timedelta | ir.IntervalValue,
) -> ir.ArrayValue:
    return ops.TimestampRange(
        start=normalize_datetime(start) if isinstance(start, str) else start,
        stop=normalize_datetime(stop) if isinstance(stop, str) else stop,
        step=step,
    ).to_expr()


def _wrap_deprecated(fn, prefix=""):
    """Deprecate the top-level geo function."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if isinstance(self, Deferred):
            method = getattr(self, fn.__name__)
            return method(*args, **kwargs)
        return fn(self, *args, **kwargs)

    wrapper.__module__ = "ibis.expr.api"
    wrapper.__qualname__ = wrapper.__name__ = prefix + fn.__name__
    dec = util.deprecated(
        instead=f"use the `{fn.__qualname__}` method instead", as_of="7.0"
    )
    return dec(wrapper)


geo_area = _wrap_deprecated(ir.GeoSpatialValue.area, "geo_")
geo_as_binary = _wrap_deprecated(ir.GeoSpatialValue.as_binary, "geo_")
geo_as_ewkb = _wrap_deprecated(ir.GeoSpatialValue.as_ewkb, "geo_")
geo_as_ewkt = _wrap_deprecated(ir.GeoSpatialValue.as_ewkt, "geo_")
geo_as_text = _wrap_deprecated(ir.GeoSpatialValue.as_text, "geo_")
geo_azimuth = _wrap_deprecated(ir.GeoSpatialValue.azimuth, "geo_")
geo_buffer = _wrap_deprecated(ir.GeoSpatialValue.buffer, "geo_")
geo_centroid = _wrap_deprecated(ir.GeoSpatialValue.centroid, "geo_")
geo_contains = _wrap_deprecated(ir.GeoSpatialValue.contains, "geo_")
geo_contains_properly = _wrap_deprecated(ir.GeoSpatialValue.contains_properly, "geo_")
geo_covers = _wrap_deprecated(ir.GeoSpatialValue.covers, "geo_")
geo_covered_by = _wrap_deprecated(ir.GeoSpatialValue.covered_by, "geo_")
geo_crosses = _wrap_deprecated(ir.GeoSpatialValue.crosses, "geo_")
geo_d_fully_within = _wrap_deprecated(ir.GeoSpatialValue.d_fully_within, "geo_")
geo_difference = _wrap_deprecated(ir.GeoSpatialValue.difference, "geo_")
geo_disjoint = _wrap_deprecated(ir.GeoSpatialValue.disjoint, "geo_")
geo_distance = _wrap_deprecated(ir.GeoSpatialValue.distance, "geo_")
geo_d_within = _wrap_deprecated(ir.GeoSpatialValue.d_within, "geo_")
geo_end_point = _wrap_deprecated(ir.GeoSpatialValue.end_point, "geo_")
geo_envelope = _wrap_deprecated(ir.GeoSpatialValue.envelope, "geo_")
geo_equals = _wrap_deprecated(ir.GeoSpatialValue.geo_equals, "geo_")
geo_geometry_n = _wrap_deprecated(ir.GeoSpatialValue.geometry_n, "geo_")
geo_geometry_type = _wrap_deprecated(ir.GeoSpatialValue.geometry_type, "geo_")
geo_intersection = _wrap_deprecated(ir.GeoSpatialValue.intersection, "geo_")
geo_intersects = _wrap_deprecated(ir.GeoSpatialValue.intersects, "geo_")
geo_is_valid = _wrap_deprecated(ir.GeoSpatialValue.is_valid, "geo_")
geo_line_locate_point = _wrap_deprecated(ir.GeoSpatialValue.line_locate_point, "geo_")
geo_line_merge = _wrap_deprecated(ir.GeoSpatialValue.line_merge, "geo_")
geo_line_substring = _wrap_deprecated(ir.GeoSpatialValue.line_substring, "geo_")
geo_length = _wrap_deprecated(ir.GeoSpatialValue.length, "geo_")
geo_max_distance = _wrap_deprecated(ir.GeoSpatialValue.max_distance, "geo_")
geo_n_points = _wrap_deprecated(ir.GeoSpatialValue.n_points, "geo_")
geo_n_rings = _wrap_deprecated(ir.GeoSpatialValue.n_rings, "geo_")
geo_ordering_equals = _wrap_deprecated(ir.GeoSpatialValue.ordering_equals, "geo_")
geo_overlaps = _wrap_deprecated(ir.GeoSpatialValue.overlaps, "geo_")
geo_perimeter = _wrap_deprecated(ir.GeoSpatialValue.perimeter, "geo_")
geo_point = _wrap_deprecated(ir.NumericValue.point, "geo_")
geo_point_n = _wrap_deprecated(ir.GeoSpatialValue.point_n, "geo_")
geo_set_srid = _wrap_deprecated(ir.GeoSpatialValue.set_srid, "geo_")
geo_simplify = _wrap_deprecated(ir.GeoSpatialValue.simplify, "geo_")
geo_srid = _wrap_deprecated(ir.GeoSpatialValue.srid, "geo_")
geo_start_point = _wrap_deprecated(ir.GeoSpatialValue.start_point, "geo_")
geo_touches = _wrap_deprecated(ir.GeoSpatialValue.touches, "geo_")
geo_transform = _wrap_deprecated(ir.GeoSpatialValue.transform, "geo_")
geo_union = _wrap_deprecated(ir.GeoSpatialValue.union, "geo_")
geo_within = _wrap_deprecated(ir.GeoSpatialValue.within, "geo_")
geo_x = _wrap_deprecated(ir.GeoSpatialValue.x, "geo_")
geo_x_max = _wrap_deprecated(ir.GeoSpatialValue.x_max, "geo_")
geo_x_min = _wrap_deprecated(ir.GeoSpatialValue.x_min, "geo_")
geo_y = _wrap_deprecated(ir.GeoSpatialValue.y, "geo_")
geo_y_max = _wrap_deprecated(ir.GeoSpatialValue.y_max, "geo_")
geo_y_min = _wrap_deprecated(ir.GeoSpatialValue.y_min, "geo_")
geo_unary_union = _wrap_deprecated(ir.GeoSpatialColumn.unary_union, "geo_")
negate = _wrap_deprecated(ir.NumericValue.negate)


@deferrable
def ifelse(condition: Any, true_expr: Any, false_expr: Any) -> ir.Value:
    """Construct a ternary conditional expression.

    Parameters
    ----------
    condition
        A boolean expression
    true_expr
        Expression to return if `condition` evaluates to `True`
    false_expr
        Expression to return if `condition` evaluates to `False` or `NULL`

    Returns
    -------
    Value : ir.Value
        The value of `true_expr` if `condition` is `True` else `false_expr`

    See Also
    --------
    [`BooleanValue.ifelse()`](./expression-numeric.qmd#ibis.expr.types.logical.BooleanValue.ifelse)

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> t = ibis.memtable({"condition": [True, False, True, None]})
    >>> ibis.ifelse(t.condition, "yes", "no")
    ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
    ┃ IfElse(condition, 'yes', 'no') ┃
    ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
    │ string                         │
    ├────────────────────────────────┤
    │ yes                            │
    │ no                             │
    │ yes                            │
    │ no                             │
    └────────────────────────────────┘

    """
    if not isinstance(condition, ir.Value):
        condition = literal(condition, type="bool")
    elif not condition.type().is_boolean():
        condition = condition.cast("bool")
    return condition.ifelse(true_expr, false_expr)


@util.deprecated(instead="use `ibis.ifelse` instead", as_of="7.0")
def where(cond, true_expr, false_expr) -> ir.Value:
    """Construct a ternary conditional expression.

    Parameters
    ----------
    cond
        Boolean conditional expression
    true_expr
        Expression to return if `cond` evaluates to `True`
    false_expr
        Expression to return if `cond` evaluates to `False` or `NULL`

    Returns
    -------
    Value : ir.Value
        The value of `true_expr` if `arg` is `True` else `false_expr`
    """
    return ifelse(cond, true_expr, false_expr)


@deferrable
def coalesce(*args: Any) -> ir.Value:
    """Return the first non-null value from `args`.

    Parameters
    ----------
    args
        Arguments from which to choose the first non-null value

    Returns
    -------
    Value
        Coalesced expression

    See Also
    --------
    [`Value.coalesce()`](#ibis.expr.types.generic.Value.coalesce)
    [`Value.fill_null()`](#ibis.expr.types.generic.Value.fill_null)

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> ibis.coalesce(None, 4, 5)
    ┌───┐
    │ 4 │
    └───┘
    """
    return ops.Coalesce(args).to_expr()


@deferrable
def greatest(*args: Any) -> ir.Value:
    """Compute the largest value among the supplied arguments.

    Parameters
    ----------
    args
        Arguments to choose from

    Returns
    -------
    Value
        Maximum of the passed arguments

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> ibis.greatest(None, 4, 5)
    ┌───┐
    │ 5 │
    └───┘
    """
    return ops.Greatest(args).to_expr()


@deferrable
def least(*args: Any) -> ir.Value:
    """Compute the smallest value among the supplied arguments.

    Parameters
    ----------
    args
        Arguments to choose from

    Returns
    -------
    Value
        Minimum of the passed arguments

    Examples
    --------
    >>> import ibis
    >>> ibis.options.interactive = True
    >>> ibis.least(None, 4, 5)
    ┌───┐
    │ 4 │
    └───┘
    """
    return ops.Least(args).to_expr()
