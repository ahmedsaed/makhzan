"""Ending a partition on a short page, and proving it safe first (technique T1).

Every partition used to pay one request to learn it had ended: WooCommerce's
Store API and Shopify's feed end on an *empty* page, and Odoo, which never
serves one, on a *repeat* of its last page. A page shorter than the page size
(or a pager that says "last") already says the same thing one request earlier.
For the Odoo shop, whose 170 leaf categories average ~2.4 pages, that request
is about a third of its cycle.

A short page that is not the last would lose the rest of the partition, and a
completed cycle would then archive it. So the stop comes in three modes, set
per source as `end_on_short_page`:

  - ``"shadow"`` (the default): today's behaviour, untouched. The adapter only
    notes the page a short-page stop *would* have ended on, and the next page
    of the partition says whether it was right: an empty page, or (Odoo) a page
    bringing no new ids, agrees; anything new is a disagreement.
  - ``"live"``: the partition ends on the short page.
  - ``"off"``: nothing is noted or changed.

The verdict often lands in the *next* run: a source paced at one page a run
reads the short page today and the page after it tomorrow. The unresolved
would-stops therefore travel in `stats.source_report.short_page.pending`, and
the pipeline hands the last run's report back (`SourceAdapter.resume_from`).

Go live only after a full cycle in shadow with zero disagreements; `make status`
shows the tally per source.
"""

from __future__ import annotations

MODES = ("shadow", "live", "off")
SHADOW, LIVE, OFF = MODES

#: Disagreements named in a run's report; the count covers every one.
_NAMED = 10


def check_mode(value: object) -> str:
    """The `end_on_short_page` setting, refusing anything but the three modes."""
    if value not in MODES:
        raise ValueError(f"end_on_short_page must be one of {MODES}, got {value!r}")
    return value  # type: ignore[return-value]


class ShortPageEnd:
    """One run's short-page decisions and, in shadow, their verdicts."""

    def __init__(self, mode: str = SHADOW) -> None:
        self.mode = check_mode(mode)
        #: partition -> (page, ids) of a would-stop whose next page is unread.
        self._pending: dict[str, tuple[int, frozenset[str]]] = {}
        self.compared = 0
        self.agreed = 0
        self.disagreements = 0
        self._disagreed: list[str] = []
        #: Requests saved (live) or that would have been saved (shadow).
        self.saved = 0
        #: Partitions that ended on a full page: a short-page stop saves nothing there.
        self.full_last_page = 0

    def restore(self, report: object) -> None:
        """Pick up the would-stops a previous run left unresolved."""
        if self.mode != SHADOW or not isinstance(report, dict):
            return
        for partition, entry in (report.get("pending") or {}).items():
            if isinstance(entry, dict) and isinstance(entry.get("page"), int):
                ids = frozenset(str(i) for i in entry.get("ids") or [])
                self._pending[str(partition)] = (entry["page"], ids)

    def page(
        self, partition: str, page: int, ids: list[str] | set[str], *, short: bool, end: bool
    ) -> bool:
        """Record one page; return True when the partition should end here.

        `short` is the adapter's reading of this page (fewer items than a full
        page, or the pager says it is the last); `end` is today's end signal
        (an empty page, a repeat). Only a short page that today's signal would
        read past is a would-stop.
        """
        if self.mode == OFF:
            return False
        ids = frozenset(str(i) for i in ids)
        if self.mode == LIVE:
            if short and not end and ids:
                self.saved += 1
                return True
            return False

        pending = self._pending.pop(partition, None)
        repeat = False
        if pending is not None:
            stop_page, stop_ids = pending
            if page == stop_page + 1:
                self.compared += 1
                # Odoo's repeat of the would-stop page. The adapter cannot call
                # it a repeat when the two pages fell in different runs, so it
                # is judged here and not taken for a would-stop of its own.
                repeat = bool(ids) and ids <= stop_ids
                if ids - stop_ids:
                    # The "last" page was not: a live stop would have lost these.
                    self.disagreements += 1
                    self._disagreed.append(f"{partition or 'default'} p{stop_page}")
                else:
                    self.agreed += 1
                    self.saved += 1
            # Any other page (a restarted partition) leaves nothing to compare.
        if short and not end and ids and not repeat:
            self._pending[partition] = (page, ids)
        elif end and pending is None and page > 1:
            self.full_last_page += 1
        return False

    def report(self) -> dict:
        """`stats.source_report.short_page`, or {} when there is nothing to say."""
        if self.mode == OFF:
            return {}
        out: dict = {"mode": self.mode}
        if self.mode == LIVE:
            out["saved"] = self.saved
            return out
        out.update(
            compared=self.compared,
            agreed=self.agreed,
            disagreements=self.disagreements,
            saved=self.saved,
            full_last_page=self.full_last_page,
        )
        if self._disagreed:
            out["disagreed"] = self._disagreed[:_NAMED]
        if self._pending:
            out["pending"] = {
                partition: {"page": page, "ids": sorted(ids)}
                for partition, (page, ids) in self._pending.items()
            }
        return out
