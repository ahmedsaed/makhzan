import { Fragment } from "react";

import type { Offer } from "@/lib/api";
import { joinNames, listingsOf, partNumbers } from "@/lib/offers";

const LINE = "text-[13px] text-ink-2 lg:text-sm";

/**
 * The part-number lines under a product's title.
 *
 * makhzan's own part number (read from the titles) always stays, and a shop
 * stating the same number outright adds "· also stated by Delta Components".
 * One number the shops state that differs from it gets its own line, with
 * whose listing it is from. Two or more different numbers: none stands under
 * the title on its own, one line names them all, and each offer row shows its
 * own (P3).
 */
export function PartNumberLines({
  partNumber,
  offers,
}: {
  partNumber: string | null;
  offers: Offer[];
}) {
  const { alsoStatedBy, stated, disagree } = partNumbers(partNumber, offers);
  return (
    <>
      {partNumber && (
        <p className={LINE}>
          Part number{" "}
          <span data-identifier className="text-ink">
            {partNumber}
          </span>
          {alsoStatedBy.length > 0 && (
            <span data-also-stated className="text-ink-3">
              {" "}
              · also stated by {joinNames(alsoStatedBy)}
            </span>
          )}
        </p>
      )}
      {stated && (
        <p data-mfr-part className={LINE}>
          Mfr. part number{" "}
          <span data-identifier className="text-ink">
            {stated.value}
          </span>{" "}
          <span className="text-ink-3">· from {listingsOf(stated.shops)}</span>
        </p>
      )}
      {disagree && (
        <p data-mfr-disagree className={LINE}>
          Shops state {disagree.length} manufacturer part numbers:{" "}
          {disagree.map((value, i) => (
            <Fragment key={value}>
              {i > 0 && ", "}
              <span data-identifier className="text-ink">
                {value}
              </span>
            </Fragment>
          ))}{" "}
          <span className="text-ink-3">· each offer shows its own</span>
        </p>
      )}
    </>
  );
}
