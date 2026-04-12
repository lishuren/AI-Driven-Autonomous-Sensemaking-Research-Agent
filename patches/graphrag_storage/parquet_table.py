# Copyright (C) 2025 Microsoft
# Licensed under the MIT License

"""A Parquet-based implementation of the Table abstraction with simulated streaming."""

from __future__ import annotations

import inspect
from io import BytesIO
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import pyarrow.parquet as pq

from graphrag_storage.tables.table import RowTransformer, Table

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from graphrag_storage.storage import Storage


def _identity(row: dict[str, Any]) -> Any:
    """Return row unchanged (default transformer)."""
    return row


def _apply_transformer(transformer: RowTransformer, row: dict[str, Any]) -> Any:
    """Apply transformer to row, handling both callables and classes.

    If transformer is a class (e.g., Pydantic model), calls it with **row.
    Otherwise calls it with row as positional argument.
    """
    if inspect.isclass(transformer):
        return transformer(**row)
    return transformer(row)


class ParquetTable(Table):
    """Simulated streaming interface for Parquet tables.

    Parquet format doesn't support true row-by-row streaming, so this
    implementation simulates streaming via:
    - Read: Loads DataFrame, yields rows via iterrows()
    - Write: Accumulates rows in memory, writes all at once on close()

    This provides API compatibility with CSVTable while maintaining
    Parquet's performance characteristics for bulk operations.
    """

    def __init__(
        self,
        storage: Storage,
        table_name: str,
        transformer: RowTransformer | None = None,
        truncate: bool = True,
    ):
        """Initialize with storage backend and table name.

        Args:
            storage: Storage instance (File, Blob, or Cosmos)
            table_name: Name of the table (e.g., "documents")
            transformer: Optional callable to transform each row before
                yielding. Receives a dict, returns a transformed dict.
                Defaults to identity (no transformation).
            truncate: If True (default), overwrite file on close.
                If False, append to existing file.
        """
        self._storage = storage
        self._table_name = table_name
        self._file_key = f"{table_name}.parquet"
        self._transformer = transformer or _identity
        self._truncate = truncate
        self._df: pd.DataFrame | None = None
        self._write_rows: list[dict[str, Any]] = []

    def __aiter__(self) -> AsyncIterator[Any]:
        """Iterate through rows one at a time.

        Loads the entire DataFrame on first iteration, then yields rows
        one at a time with the transformer applied.

        Yields
        ------
            Any:
                Each row as dict or transformed type (e.g., Pydantic model).
        """
        return self._aiter_impl()

    async def _aiter_impl(self) -> AsyncIterator[Any]:
        """Implement async iteration over rows.

        Notes
        -----
        Uses ``pq.ParquetFile.iter_batches()`` rather than ``pd.read_parquet()``
        to work around a PyArrow >=22.0 bug: converting a ``ChunkedArray`` with
        a nested type (e.g. ``list<string>``) to pandas raises
        ``ArrowNotImplementedError`` when the file has multiple row groups.
        ``iter_batches()`` yields ``RecordBatch`` (non-chunked), which converts
        without error.
        """
        if self._df is None:
            if await self._storage.has(self._file_key):
                data = await self._storage.get(self._file_key, as_bytes=True)
                # Work around PyArrow >=22 bug: ChunkedArray-to-pandas fails for
                # nested types in multi-row-group files; iter_batches() is safe.
                pf = pq.ParquetFile(BytesIO(data))
                frames = [batch.to_pandas() for batch in pf.iter_batches()]
                self._df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            else:
                self._df = pd.DataFrame()

        # to_dict('records') is ~50-100x faster than iterrows() for large
        # DataFrames because it avoids creating a pandas Series per row.
        for row_dict in self._df.to_dict("records"):
            yield _apply_transformer(self._transformer, cast("dict[str, Any]", row_dict))

    async def length(self) -> int:
        """Return the number of rows in the table.

        Notes
        -----
        Same PyArrow >=22.0 workaround as ``_aiter_impl``.
        """
        if self._df is None:
            if await self._storage.has(self._file_key):
                data = await self._storage.get(self._file_key, as_bytes=True)
                # Work around PyArrow >=22 bug: same fix as _aiter_impl.
                pf = pq.ParquetFile(BytesIO(data))
                frames = [batch.to_pandas() for batch in pf.iter_batches()]
                self._df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            else:
                return 0
        return len(self._df)

    async def has(self, row_id: str) -> bool:
        """Check if row with given ID exists."""
        async for row in self:
            if isinstance(row, dict):
                if row.get("id") == row_id:
                    return True
            elif getattr(row, "id", None) == row_id:
                return True
        return False

    async def write(self, row: dict[str, Any]) -> None:
        """Accumulate a single row for later batch write.

        Rows are stored in memory and written to Parquet format
        when close() is called.

        Args
        ----
            row: Dictionary representing a single row to write.
        """
        self._write_rows.append(row)

    async def close(self) -> None:
        """Flush accumulated rows to Parquet file and release resources.

        Converts all accumulated rows to a DataFrame and writes
        to storage as a Parquet file. If truncate=False and file exists,
        appends to existing data.

        Notes
        -----
        Same PyArrow >=22.0 workaround as ``_aiter_impl`` when reading the
        existing file for append mode.
        """
        if self._write_rows:
            new_df = pd.DataFrame(self._write_rows)
            if not self._truncate and await self._storage.has(self._file_key):
                existing_data = await self._storage.get(self._file_key, as_bytes=True)
                # Work around PyArrow >=22 bug: same fix as _aiter_impl.
                pf = pq.ParquetFile(BytesIO(existing_data))
                frames = [batch.to_pandas() for batch in pf.iter_batches()]
                existing_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                new_df = pd.concat([existing_df, new_df], ignore_index=True)
            await self._storage.set(self._file_key, new_df.to_parquet())
            self._write_rows = []

        self._df = None
