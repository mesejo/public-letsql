"""BigQuery ibis client implementation."""

from __future__ import annotations

import contextlib
import functools

import dateutil.parser
import google.cloud.bigquery as bq

import xorq.common.exceptions as com
import xorq.vendor.ibis.expr.datatypes as dt
from xorq.vendor.ibis.backends.bigquery.datatypes import BigQuerySchema, BigQueryType


NATIVE_PARTITION_COL = "_PARTITIONTIME"


def schema_from_bigquery_table(table, *, wildcard: bool):
    schema = BigQuerySchema.to_ibis(table.schema)

    # Check for partitioning information
    partition_info = table.time_partitioning
    if partition_info is not None:
        # We have a partitioned table
        partition_field = partition_info.field or NATIVE_PARTITION_COL
        # Only add a new column if it's not already a column in the schema
        if partition_field not in schema:
            schema |= {partition_field: dt.Timestamp(timezone="UTC")}

    if wildcard:
        schema |= {"_TABLE_SUFFIX": dt.string}

    return schema


@functools.singledispatch
def bigquery_param(dtype, value, name):
    raise NotADirectoryError(dtype)


@bigquery_param.register
def bq_param_struct(dtype: dt.Struct, value, name):
    fields = dtype.fields
    field_params = [bigquery_param(fields[k], v, k) for k, v in value.items()]
    result = bq.StructQueryParameter(name, *field_params)
    return result


@bigquery_param.register
def bq_param_array(dtype: dt.Array, value, name):
    value_type = dtype.value_type

    try:
        bigquery_type = BigQueryType.to_string(value_type)
    except NotImplementedError:
        raise com.UnsupportedBackendType(dtype)
    else:
        if isinstance(value_type, dt.Array):
            raise TypeError("ARRAY<ARRAY<T>> is not supported in BigQuery")
        elif isinstance(value_type, dt.Struct):
            query_value = [
                bigquery_param(dtype.value_type, struct, f"element_{i:d}")
                for i, struct in enumerate(value)
            ]
            bigquery_type = "STRUCT"
        else:
            query_value = value
        return bq.ArrayQueryParameter(name, bigquery_type, query_value)


@bigquery_param.register
def bq_param_timestamp(_: dt.Timestamp, value, name):
    with contextlib.suppress(TypeError):
        value = dateutil.parser.parse(value)
    return bq.ScalarQueryParameter(name, "TIMESTAMP", value.isoformat())


@bigquery_param.register
def bq_param_string(_: dt.String, value, name):
    return bq.ScalarQueryParameter(name, "STRING", value)


@bigquery_param.register
def bq_param_integer(_: dt.Integer, value, name):
    return bq.ScalarQueryParameter(name, "INT64", value)


@bigquery_param.register
def bq_param_double(_: dt.Floating, value, name):
    return bq.ScalarQueryParameter(name, "FLOAT64", value)


@bigquery_param.register
def bq_param_boolean(_: dt.Boolean, value, name):
    return bq.ScalarQueryParameter(name, "BOOL", value)


@bigquery_param.register
def bq_param_date(_: dt.Date, value, name):
    with contextlib.suppress(TypeError):
        value = dateutil.parser.parse(value)

    with contextlib.suppress(AttributeError):
        value = value.date()

    return bq.ScalarQueryParameter(name, "DATE", value.isoformat())


def rename_partitioned_column(table_expr, bq_table, partition_col):
    """Rename native partition column to user-defined name."""
    partition_info = bq_table.time_partitioning

    # If we don't have any partition information, the table isn't partitioned
    if partition_info is None:
        return table_expr

    # If we have a partition, but no "field" field in the table properties,
    # then use NATIVE_PARTITION_COL as the default
    partition_field = partition_info.field or NATIVE_PARTITION_COL

    # The partition field must be in table_expr columns
    assert partition_field in table_expr.columns

    # No renaming if the config option is set to None or the partition field
    # is not _PARTITIONTIME
    if partition_col is None or partition_field != NATIVE_PARTITION_COL:
        return table_expr
    return table_expr.rename({partition_col: NATIVE_PARTITION_COL})


def parse_project_and_dataset(project: str, dataset: str = "") -> tuple[str, str, str]:
    """Compute the billing project, data project, and dataset if available.

    This function figure out the project id under which queries will run versus
    the project of where the data live as well as what dataset to use.

    Parameters
    ----------
    project : str
        A project name
    dataset : Optional[str]
        A `<project>.<dataset>` string or just a dataset name

    Examples
    --------
    >>> data_project, billing_project, dataset = parse_project_and_dataset(
    ...     "ibis-gbq", "foo-bar.my_dataset"
    ... )
    >>> data_project
    'foo-bar'
    >>> billing_project
    'ibis-gbq'
    >>> dataset
    'my_dataset'
    >>> data_project, billing_project, dataset = parse_project_and_dataset(
    ...     "ibis-gbq", "my_dataset"
    ... )
    >>> data_project
    'ibis-gbq'
    >>> billing_project
    'ibis-gbq'
    >>> dataset
    'my_dataset'
    >>> data_project, billing_project, _dataset = parse_project_and_dataset("ibis-gbq")
    >>> data_project
    'ibis-gbq'

    """
    if dataset.count(".") > 1:
        raise ValueError(
            f"{dataset} is not a BigQuery dataset. More info https://cloud.google.com/bigquery/docs/datasets-intro"
        )
    elif dataset.count(".") == 1:
        data_project, dataset = dataset.split(".")
        billing_project = project
    else:
        billing_project = data_project = project

    return data_project, billing_project, dataset
