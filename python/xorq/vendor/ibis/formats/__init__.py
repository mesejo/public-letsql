from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from xorq.vendor.ibis.util import PseudoHashable, indent


if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa

    from xorq.vendor.ibis.expr.datatypes import DataType
    from xorq.vendor.ibis.expr.schema import Schema

C = TypeVar("C")
T = TypeVar("T")
S = TypeVar("S")


class TypeMapper(Generic[T]):
    # `T` is the format-specific type object, e.g. pyarrow.DataType

    @classmethod
    def from_ibis(cls, dtype: DataType) -> T:
        """Convert an Ibis DataType to a format-specific type object.

        Parameters
        ----------
        dtype
            The Ibis DataType to convert.

        Returns
        -------
        Format-specific type object.

        """
        raise NotImplementedError

    @classmethod
    def to_ibis(cls, typ: T, nullable: bool = True) -> DataType:
        """Convert a format-specific type object to an Ibis DataType.

        Parameters
        ----------
        typ
            The format-specific type object to convert.
        nullable
            Whether the Ibis DataType should be nullable.

        Returns
        -------
        Ibis DataType.

        """
        raise NotImplementedError

    @classmethod
    def from_string(cls, text: str, nullable: bool = True) -> DataType:
        """Convert a backend-specific string representation into an Ibis DataType.

        Parameters
        ----------
        text
            The backend-specific string representation to convert.
        nullable
            Whether the Ibis DataType should be nullable.

        Returns
        -------
        Ibis DataType.

        """
        raise NotImplementedError

    @classmethod
    def to_string(cls, dtype: DataType) -> str:
        """Convert `dtype` into a backend-specific string representation.

        Parameters
        ----------
        dtype
            The Ibis DataType to convert.

        Returns
        -------
        Backend-specific string representation.

        """
        raise NotImplementedError


class SchemaMapper(Generic[S]):
    # `S` is the format-specific schema object, e.g. pyarrow.Schema

    @classmethod
    def from_ibis(cls, schema: Schema) -> S:
        """Convert an Ibis Schema to a format-specific schema object.

        Parameters
        ----------
        schema
            The Ibis Schema to convert.

        Returns
        -------
        Format-specific schema object.

        """
        raise NotImplementedError

    @classmethod
    def to_ibis(cls, obj: S) -> Schema:
        """Convert a format-specific schema object to an Ibis Schema.

        Parameters
        ----------
        obj
            The format-specific schema object to convert.

        Returns
        -------
        Ibis Schema.

        """
        raise NotImplementedError


class DataMapper(Generic[S, C, T]):
    # `S` is the format-specific scalar object, e.g. pyarrow.Scalar
    # `C` is the format-specific column object, e.g. pyarrow.Array
    # `T` is the format-specific table object, e.g. pyarrow.Table

    @classmethod
    def convert_scalar(cls, obj: S, dtype: DataType) -> S:
        """Convert a format-specific scalar to the given ibis datatype.

        Parameters
        ----------
        obj
            The format-specific scalar value to convert.
        dtype
            The Ibis datatype to convert to.

        Returns
        -------
        Format specific scalar corresponding to the given Ibis datatype.

        """
        raise NotImplementedError

    @classmethod
    def convert_column(cls, obj: C, dtype: DataType) -> C:
        """Convert a format-specific column to the given ibis datatype.

        Parameters
        ----------
        obj
            The format-specific column value to convert.
        dtype
            The Ibis datatype to convert to.

        Returns
        -------
        Format specific column corresponding to the given Ibis datatype.

        """
        raise NotImplementedError

    @classmethod
    def convert_table(cls, obj: T, schema: Schema) -> T:
        """Convert a format-specific table to the given ibis schema.

        Parameters
        ----------
        obj
            The format-specific table-like object to convert.
        schema
            The Ibis schema to convert to.

        Returns
        -------
        Format specific table-like object corresponding to the given Ibis schema.

        """
        raise NotImplementedError

    @classmethod
    def infer_scalar(cls, obj: S) -> DataType:
        """Infer the Ibis datatype of a format-specific scalar.

        Parameters
        ----------
        obj
            The format-specific scalar to infer the Ibis datatype of.

        Returns
        -------
        Ibis datatype corresponding to the given format-specific scalar.

        """
        raise NotImplementedError

    @classmethod
    def infer_column(cls, obj: C) -> DataType:
        """Infer the Ibis datatype of a format-specific column.

        Parameters
        ----------
        obj
            The format-specific column to infer the Ibis datatype of.

        Returns
        -------
        Ibis datatype corresponding to the given format-specific column.

        """
        raise NotImplementedError

    @classmethod
    def infer_table(cls, obj: T) -> Schema:
        """Infer the Ibis schema of a format-specific table.

        Parameters
        ----------
        obj
            The format-specific table to infer the Ibis schema of.

        Returns
        -------
        Ibis schema corresponding to the given format-specific table.

        """
        raise NotImplementedError


class TableProxy(PseudoHashable[T]):
    def __repr__(self) -> str:
        data_repr = indent(repr(self.obj), spaces=2)
        return f"{self.__class__.__name__}:\n{data_repr}"

    def __len__(self) -> int:
        return len(self.obj)

    @abstractmethod
    def to_frame(self) -> pd.DataFrame:  # pragma: no cover
        """Convert this input to a pandas DataFrame."""

    @abstractmethod
    def to_pyarrow(self, schema: Schema) -> pa.Table:  # pragma: no cover
        """Convert this input to a PyArrow Table."""

    @abstractmethod
    def to_polars(self, schema: Schema) -> pl.DataFrame:  # pragma: no cover
        """Convert this input to a Polars DataFrame."""

    def to_pyarrow_bytes(self, schema: Schema) -> bytes:
        import pyarrow as pa
        import pyarrow_hotfix  # noqa: F401

        data = self.to_pyarrow(schema=schema)
        out = pa.BufferOutputStream()
        with pa.RecordBatchFileWriter(out, data.schema) as writer:
            writer.write(data)
        return out.getvalue()
