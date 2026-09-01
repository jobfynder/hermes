import { useEffect, useMemo, useState } from 'react'

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200]

/** Client-side pagination over an already-filtered/sorted array -- every
 * one of these lists is small enough in bytes to fetch in one call
 * (already true before this existed), the actual cost at scale was
 * rendering thousands of table rows into the DOM at once. Slicing here
 * caps that without changing how filtering/search/sort already work
 * (they still run over the full list, pagination only affects display).
 *
 * resetKey resets to page 1 when it changes -- pass something derived
 * from the page's own filter/search/sort state (e.g. `${search}|
 * ${typeFilter}`), NOT the items array itself: a page like the drafts
 * list auto-refreshes its data on a timer, and resetting on every data
 * refresh would silently kick a reviewer back to page 1 every 30
 * seconds while they're reading page 3. If the data shrinks out from
 * under the current page (an item got deleted/approved elsewhere), the
 * page number is clamped to the new last page rather than reset.
 */
export function usePagination<T>(items: T[], resetKey: string | number, defaultPageSize = 50) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(defaultPageSize)

  useEffect(() => {
    setPage(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey])

  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const clampedPage = Math.min(page, pageCount)

  const pageItems = useMemo(() => {
    const start = (clampedPage - 1) * pageSize
    return items.slice(start, start + pageSize)
  }, [items, clampedPage, pageSize])

  return {
    pageItems,
    page: clampedPage,
    pageCount,
    pageSize,
    setPage,
    setPageSize: (size: number) => {
      setPageSize(size)
      setPage(1)
    },
  }
}

export function PaginationControls({
  page,
  pageCount,
  pageSize,
  totalCount,
  onPageChange,
  onPageSizeChange,
}: {
  page: number
  pageCount: number
  pageSize: number
  totalCount: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}) {
  if (totalCount === 0) return null

  const start = totalCount === 0 ? 0 : (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, totalCount)

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-xs text-ink-soft">
      <span>
        {start}–{end} of {totalCount}
      </span>
      <div className="flex items-center gap-3">
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded border border-line bg-paper px-2 py-1 text-xs text-ink outline-none focus:border-accent"
        >
          {PAGE_SIZE_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n} / page
            </option>
          ))}
        </select>
        <div className="flex items-center gap-1.5">
          <button
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
            className="rounded border border-line px-2 py-1 text-xs text-ink-soft transition hover:text-ink disabled:opacity-40"
          >
            Prev
          </button>
          <span>
            Page {page} of {pageCount}
          </span>
          <button
            disabled={page >= pageCount}
            onClick={() => onPageChange(page + 1)}
            className="rounded border border-line px-2 py-1 text-xs text-ink-soft transition hover:text-ink disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
