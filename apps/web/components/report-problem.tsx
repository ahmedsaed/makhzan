"use client";

import { Dialog } from "@base-ui/react/dialog";
import { Check, Flag, Search, TriangleAlert, X } from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { Link } from "@/components/link";
import { formatPriceRange } from "@/lib/format";
import {
  apiBase,
  blankForm,
  buildPayload,
  candidateMeta,
  CONTACT_FIELDS,
  DETAIL_FIELDS,
  emailFallback,
  fetchOpenedToken,
  type FieldErrors,
  type FormState,
  type Limited,
  limitedTitle,
  MAX_DESCRIPTION,
  PRICE_FIELDS,
  type PickedProduct,
  productIdFromLink,
  reasonOf,
  reasonsFor,
  type ReportContext,
  type ReportOffer,
  several,
  shopsOf,
  STOCK_VALUES,
  submitReport,
  validate,
  waitText,
} from "@/lib/report";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

type Status = "idle" | "sending" | "sent" | "error" | "limited";

/** Where focus goes first when a field is in error, by error key. */
const ERROR_TARGET: Record<keyof FieldErrors, string> = {
  reason: 'input[name="reason"]',
  offers: 'input[name="offers"]',
  other: "[data-report-combo]",
  priceOffer: 'input[name="priceOffer"]',
  field: 'input[name="field"]',
  detailField: 'input[name="detailField"]',
  contactShop: "#report-contact-shop",
  contactField: 'input[name="contactField"]',
  description: "#report-description",
  email: "#report-email",
};

/**
 * "Report a problem": a button beside the product's title, and the form it
 * opens (docs/DESIGN.md, the approved mockup of November 2026).
 *
 * A Base UI Dialog: focus is trapped inside while it is open, the page behind
 * stops scrolling, Esc and the close button shut it, and focus returns to the
 * button. A centred dialog from `sm`; a sheet from the bottom on a phone.
 *
 * Two steps: what is wrong, then the few details that reason needs, an
 * optional note and an optional email. Each offer is listed in step two, so
 * the visitor ticks which ones are wrong there; there is no button per offer.
 * The rules live in lib/report.ts; the API checks them again and keeps the
 * spam rules and limits. Nothing loads from anyone else, and nothing is sent
 * until "Send report".
 */
export function ReportProblem({ context }: { context: ReportContext }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(blankForm);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<Status>("idle");
  const [limited, setLimited] = useState<Limited | null>(null);
  const [reference, setReference] = useState<string | null>(null);
  const [sentAt, setSentAt] = useState<Date | null>(null);
  /** When the form opened, as the API signed it; asked for on opening. */
  const openedToken = useRef<Promise<string | null> | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  /** True while the product search's list is open: Esc closes the list, not the dialog. */
  const listOpen = useRef(false);
  const onListOpen = useCallback((value: boolean) => {
    listOpen.current = value;
  }, []);
  /** Bumped on every send and close, so a reply to a send the visitor gave up on is ignored. */
  const attempt = useRef(0);
  const focusHeading = useRef(false);

  const patch = (change: Partial<FormState>) => setForm((current) => ({ ...current, ...change }));
  const clearError = (key: keyof FieldErrors) =>
    setErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });

  useEffect(() => {
    if (!focusHeading.current) return;
    focusHeading.current = false;
    heading.current?.focus();
    body.current?.scrollTo?.({ top: 0 });
    // The step's buttons may have just been replaced, and the dialog's focus
    // trap, finding the focused button gone, moves focus to the dialog itself
    // a moment later. Land on the heading after it has.
    setTimeout(() => {
      const popupEl = popup.current;
      const focused = document.activeElement;
      if (popupEl && (focused === popupEl || focused === document.body)) heading.current?.focus();
    }, 50);
  });

  const reset = () => {
    setForm(blankForm());
    setErrors({});
    setStatus("idle");
    setLimited(null);
    setReference(null);
  };

  const onOpenChange = (next: boolean, details: Dialog.Root.ChangeEventDetails) => {
    if (!next && details.reason === "escape-key" && listOpen.current) return;
    if (next) {
      // A token per opening: the API counts its 3 s from here.
      openedToken.current = fetchOpenedToken();
      if (status === "sent") reset();
    } else {
      attempt.current += 1;
      // A report that went is done with; one that did not keeps its draft.
      if (status === "sent") reset();
      else if (status === "sending") setStatus("idle");
    }
    setOpen(next);
  };

  const focusFirstError = (found: FieldErrors) => {
    const first = (Object.keys(ERROR_TARGET) as (keyof FieldErrors)[]).find((key) => found[key]);
    if (!first) return;
    requestAnimationFrame(() =>
      popup.current?.querySelector<HTMLElement>(ERROR_TARGET[first])?.focus(),
    );
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (status === "sending") return;
    const found = validate(form, context);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      focusFirstError(found);
      return;
    }
    if (form.step === 1) {
      focusHeading.current = true;
      patch({ step: 2 });
      setStatus("idle");
      return;
    }
    const mine = ++attempt.current;
    setStatus("sending");
    // Asked for when the dialog opened; once more if that failed. Without
    // one the API would drop the report unseen, so say it was not sent.
    let token = await (openedToken.current ?? Promise.resolve(null));
    if (!token) {
      openedToken.current = fetchOpenedToken();
      token = await openedToken.current;
    }
    const result = token
      ? await submitReport(buildPayload(form, context, token))
      : ({ kind: "error" } as const);
    if (mine !== attempt.current) return;
    if (result.kind === "sent") {
      setReference(result.reference);
      setSentAt(new Date());
      focusHeading.current = true;
      setStatus("sent");
    } else if (result.kind === "limited") {
      setLimited(result);
      setStatus("limited");
      body.current?.scrollTo?.({ top: 0 });
    } else {
      setStatus("error");
      body.current?.scrollTo?.({ top: 0 });
    }
  };

  const back = () => {
    focusHeading.current = true;
    setErrors({});
    setStatus("idle");
    patch({ step: 1 });
  };

  const sending = status === "sending";
  const reason = reasonOf(form.reason);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Trigger
        data-report-button
        aria-label="Report a problem"
        className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-control border-[1.5px] border-line-strong bg-surface px-3 text-[13.5px] font-semibold text-ink hover:border-link max-sm:w-11 max-sm:justify-center max-sm:px-0 lg:min-h-[34px]"
      >
        <Flag aria-hidden="true" className="size-[15px] shrink-0 text-ink-2" />
        <span className="max-sm:hidden">Report a problem</span>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-scrim/60" />
        <Dialog.Popup
          ref={popup}
          data-report-dialog
          initialFocus={heading}
          className="fixed inset-x-0 bottom-0 z-50 flex max-h-[calc(100dvh-12px)] flex-col rounded-t-card border border-b-0 border-line bg-surface text-ink outline-none sm:inset-x-auto sm:top-1/2 sm:bottom-auto sm:left-1/2 sm:max-h-[min(780px,calc(100dvh-48px))] sm:w-[min(560px,calc(100vw-32px))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-card sm:border-b"
        >
          <div
            aria-hidden="true"
            className="mx-auto mt-2 h-1 w-9 rounded-full bg-line-strong sm:hidden"
          />
          <div className="flex items-start gap-2 border-b border-line py-2 ps-4 pe-2 sm:ps-5 sm:pe-2.5 sm:pt-3.5 sm:pb-3">
            <div className="min-w-0 flex-1 pt-2">
              <Dialog.Title className="text-lg leading-tight">Report a problem</Dialog.Title>
              <p data-report-about className="mt-0.5 truncate text-[13px] text-ink-2">
                {context.title}
              </p>
            </div>
            <Dialog.Close
              aria-label="Close"
              className="grid size-11 shrink-0 place-items-center rounded-control text-ink-2 hover:bg-ground"
            >
              <X aria-hidden="true" className="size-5" />
            </Dialog.Close>
          </div>
          <form noValidate onSubmit={onSubmit} className="contents">
            <div
              ref={body}
              className="overflow-y-auto overscroll-contain px-4 pt-3.5 pb-4.5 sm:px-5 sm:pt-4 sm:pb-5"
            >
              {status === "sent" ? (
                <Sent
                  heading={heading}
                  matching={form.reason === "offers_not_same" || form.reason === "same_as_other"}
                  email={form.email.trim()}
                  reference={reference}
                  sentAt={sentAt}
                />
              ) : (
                <fieldset disabled={sending} className="contents">
                  {status === "error" && (
                    <Alert title="Your report wasn’t sent.">
                      Nothing you wrote is lost. Try again, or{" "}
                      <a
                        href={emailFallback(form, context)}
                        data-contact="report"
                        className="font-semibold text-inherit underline"
                      >
                        email it to us
                      </a>
                      .
                    </Alert>
                  )}
                  {status === "limited" && limited && (
                    <Alert title={limitedTitle(limited)}>
                      To keep makhzan free of spam, please wait {waitText(limited.minutes)}, or{" "}
                      <a
                        href={emailFallback(form, context)}
                        data-contact="report"
                        className="font-semibold text-inherit underline"
                      >
                        email it to us
                      </a>
                      . Your text is still here.
                    </Alert>
                  )}
                  {form.step === 1 ? (
                    <StepOne
                      heading={heading}
                      context={context}
                      form={form}
                      error={errors.reason}
                      onChoose={(key) => {
                        patch({ reason: key });
                        clearError("reason");
                      }}
                    />
                  ) : (
                    <StepTwo
                      heading={heading}
                      title={reason?.title ?? "Something else"}
                      context={context}
                      form={form}
                      errors={errors}
                      patch={patch}
                      clearError={clearError}
                      onListOpen={onListOpen}
                    />
                  )}
                </fieldset>
              )}
            </div>
            <div className="flex gap-2.5 rounded-b-card border-t border-line bg-surface px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:justify-end sm:px-5 sm:pb-3">
              {status === "sent" ? (
                <Dialog.Close className={cn(PRIMARY, "flex-1 sm:flex-none")}>Close</Dialog.Close>
              ) : form.step === 1 ? (
                <>
                  <Dialog.Close className={SECONDARY}>Cancel</Dialog.Close>
                  <button type="submit" className={cn(PRIMARY, "flex-1 sm:flex-none")}>
                    Continue
                  </button>
                </>
              ) : (
                <>
                  <button type="button" onClick={back} disabled={sending} className={SECONDARY}>
                    Back
                  </button>
                  <button
                    type="submit"
                    aria-disabled={sending || undefined}
                    className={cn(
                      PRIMARY,
                      "flex-1 sm:flex-none",
                      sending && "cursor-progress opacity-70",
                    )}
                  >
                    {sending ? (
                      <>
                        <span
                          aria-hidden="true"
                          className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:animate-none"
                        />
                        Sending…
                      </>
                    ) : (
                      "Send report"
                    )}
                  </button>
                </>
              )}
            </div>
          </form>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const BUTTON =
  "inline-flex min-h-12 items-center justify-center gap-1.5 rounded-control px-4.5 text-[15px] font-semibold sm:min-h-11";
const PRIMARY = cn(BUTTON, "bg-action text-action-ink");
const SECONDARY = cn(
  BUTTON,
  "border-[1.5px] border-line-strong bg-surface text-ink disabled:opacity-60",
);

/** A card holding a radio or a checkbox: the whole card is the label. */
const CARD =
  "flex cursor-pointer items-start gap-3 rounded-control border-[1.5px] border-line-strong bg-surface px-3.5 py-2.5 hover:border-ink-3 has-checked:border-link has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-link";
const CARD_INPUT = "mt-0.5 size-5 shrink-0 accent-action";
const STEP = "mb-1 text-xs font-semibold tracking-[0.02em] text-ink-2 uppercase";
const QUESTION = "mb-2.5 text-base outline-none";
const LABEL = "mb-1.5 block text-sm font-semibold";
const OPTIONAL = "font-normal text-ink-2";
const HINT = "mb-2 text-[13px] text-ink-2";
const INPUT =
  "min-h-11 w-full rounded-control border-[1.5px] border-line-strong bg-surface px-3 py-2.5 text-base placeholder:text-ink-3 focus:outline-2 focus:outline-offset-1 focus:outline-link aria-invalid:border-ink";

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p
      id={id}
      data-field-error
      className="mt-2 flex items-start gap-1.5 rounded-control border border-warn-line bg-warn px-2.5 py-1.5 text-[13px] font-medium text-warn-ink"
    >
      <TriangleAlert aria-hidden="true" className="mt-px size-4 shrink-0" />
      <span>{message}</span>
    </p>
  );
}

function Alert({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div
      role="alert"
      data-report-alert
      className="mb-3.5 flex items-start gap-2.5 rounded-control border border-warn-line bg-warn px-3 py-2.5 text-sm text-warn-ink"
    >
      <TriangleAlert aria-hidden="true" className="mt-0.5 size-[18px] shrink-0" />
      <span>
        <b className="block">{title}</b>
        {children}
      </span>
    </div>
  );
}

function StepOne({
  heading,
  context,
  form,
  error,
  onChoose,
}: {
  heading: React.RefObject<HTMLHeadingElement | null>;
  context: ReportContext;
  form: FormState;
  error?: string;
  onChoose: (key: FormState["reason"] & string) => void;
}) {
  return (
    <>
      <p className={STEP}>Step 1 of 2</p>
      <fieldset aria-describedby={error ? "report-err-reason" : undefined}>
        <legend className="contents">
          <h3 ref={heading} tabIndex={-1} id="report-question" className={QUESTION}>
            What’s wrong?
          </h3>
        </legend>
        <div className="flex flex-col gap-2">
          {reasonsFor(context).map((reason) => (
            <label key={reason.key} className={cn(CARD, "min-h-13")}>
              <input
                type="radio"
                name="reason"
                value={reason.key}
                checked={form.reason === reason.key}
                onChange={() => onChoose(reason.key)}
                className={CARD_INPUT}
              />
              <span className="flex min-w-0 flex-col gap-px">
                <b className="text-[15px] font-semibold">{reason.title}</b>
                {reason.hint && <span className="text-[13px] text-ink-2">{reason.hint}</span>}
              </span>
            </label>
          ))}
        </div>
        <FieldError id="report-err-reason" message={error} />
      </fieldset>
    </>
  );
}

function OfferLabel({ offer }: { offer: ReportOffer }) {
  return (
    <span className="flex min-w-0 flex-col gap-px">
      <b dir="auto" className="text-[15px] font-semibold">
        {offer.title}
      </b>
      <span className="text-[13px] text-ink-2">
        {offer.shop?.name ?? "A shop"} ·{" "}
        <span className="figure text-sm text-ink">{offer.price}</span>
        {offer.outOfStock && " · out of stock"}
        {offer.stale && " · out of date"}
      </span>
    </span>
  );
}

function Chips<V extends string>({
  name,
  options,
  value,
  onChange,
}: {
  name: string;
  options: readonly (readonly [V, string])[];
  value: V | null;
  onChange: (value: V) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map(([key, label]) => (
        <label key={key} className="relative">
          <input
            type="radio"
            name={name}
            value={key}
            checked={value === key}
            onChange={() => onChange(key)}
            className="peer absolute inset-0 m-0 cursor-pointer opacity-0"
          />
          <span className="inline-flex min-h-11 items-center rounded-full border-[1.5px] border-line-strong bg-surface px-3.5 text-sm font-medium peer-checked:border-chip-on peer-checked:bg-chip-on peer-checked:text-chip-on-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-link lg:min-h-[38px]">
            {label}
          </span>
        </label>
      ))}
    </div>
  );
}

function StepTwo({
  heading,
  title,
  context,
  form,
  errors,
  patch,
  clearError,
  onListOpen,
}: {
  heading: React.RefObject<HTMLHeadingElement | null>;
  title: string;
  context: ReportContext;
  form: FormState;
  errors: FieldErrors;
  patch: (change: Partial<FormState>) => void;
  clearError: (key: keyof FieldErrors) => void;
  onListOpen: (open: boolean) => void;
}) {
  const required = form.reason === "other";
  const many = several(context);
  const shops = shopsOf(context);
  const described = (...ids: (string | false | undefined)[]) =>
    ids.filter(Boolean).join(" ") || undefined;
  return (
    <>
      <p className={STEP}>Step 2 of 2</p>
      <h3 ref={heading} tabIndex={-1} id="report-question" className={QUESTION}>
        {title}
      </h3>

      {form.reason === "offers_not_same" && (
        <fieldset
          className="mt-4"
          aria-describedby={errors.offers ? "report-err-offers" : undefined}
        >
          <legend className={LABEL}>Which offers are a different product?</legend>
          <p className={HINT}>
            Tick each one that doesn’t match. All {context.offers.length} offers are here, out of
            stock and out of date included.
          </p>
          <div className="flex flex-col gap-2">
            {context.offers.map((offer) => (
              <label key={offer.id} className={cn(CARD, "min-h-11 py-2")}>
                <input
                  type="checkbox"
                  name="offers"
                  value={offer.id}
                  checked={form.offers.includes(offer.id)}
                  onChange={(event) => {
                    patch({
                      offers: event.target.checked
                        ? [...form.offers, offer.id]
                        : form.offers.filter((id) => id !== offer.id),
                    });
                    clearError("offers");
                  }}
                  className={CARD_INPUT}
                />
                <OfferLabel offer={offer} />
              </label>
            ))}
          </div>
          <FieldError id="report-err-offers" message={errors.offers} />
        </fieldset>
      )}

      {form.reason === "same_as_other" && (
        <ProductPicker
          context={context}
          picked={form.other}
          error={errors.other}
          onListOpen={onListOpen}
          onPick={(other) => {
            patch({ other });
            clearError("other");
          }}
        />
      )}

      {form.reason === "wrong_price_stock" && (
        <>
          {many ? (
            <fieldset
              className="mt-4"
              aria-describedby={errors.priceOffer ? "report-err-priceOffer" : undefined}
            >
              <legend className={LABEL}>Which offer?</legend>
              <div className="flex flex-col gap-2">
                {context.offers.map((offer) => (
                  <label key={offer.id} className={cn(CARD, "min-h-11 py-2")}>
                    <input
                      type="radio"
                      name="priceOffer"
                      value={offer.id}
                      checked={form.priceOffer === offer.id}
                      onChange={() => {
                        patch({ priceOffer: offer.id });
                        clearError("priceOffer");
                      }}
                      className={CARD_INPUT}
                    />
                    <OfferLabel offer={offer} />
                  </label>
                ))}
              </div>
              <FieldError id="report-err-priceOffer" message={errors.priceOffer} />
            </fieldset>
          ) : (
            context.offers[0] && (
              <p className={cn(HINT, "mt-1")}>
                About the offer at {context.offers[0].shop?.name ?? "the shop"},{" "}
                {context.offers[0].price}.
              </p>
            )
          )}
          <fieldset
            className="mt-4"
            aria-describedby={errors.field ? "report-err-field" : undefined}
          >
            <legend className={LABEL}>What’s wrong with it?</legend>
            <Chips
              name="field"
              options={PRICE_FIELDS}
              value={form.field}
              onChange={(field) => {
                patch({ field });
                clearError("field");
              }}
            />
            <FieldError id="report-err-field" message={errors.field} />
          </fieldset>
          {form.field === "price" && (
            <div className="mt-4">
              <label htmlFor="report-value" className={LABEL}>
                Price on the shop’s site <span className={OPTIONAL}>(optional)</span>
              </label>
              <div className="relative">
                <span
                  aria-hidden="true"
                  className="absolute top-1/2 left-3 -translate-y-1/2 text-[15px] text-ink-2"
                >
                  EGP
                </span>
                <input
                  id="report-value"
                  name="value"
                  inputMode="decimal"
                  autoComplete="off"
                  value={form.value}
                  onChange={(event) => patch({ value: event.target.value })}
                  aria-describedby="report-value-hint"
                  className={cn(INPUT, "ps-12 tabular")}
                />
              </div>
              <p id="report-value-hint" className={cn(HINT, "mt-1.5 mb-0")}>
                The price of one, as the shop shows it today.
              </p>
            </div>
          )}
          {form.field === "stock" && (
            <fieldset className="mt-4">
              <legend className={LABEL}>
                On the shop’s site it is <span className={OPTIONAL}>(optional)</span>
              </legend>
              <Chips
                name="stockValue"
                options={STOCK_VALUES}
                value={form.stockValue}
                onChange={(stockValue) => patch({ stockValue })}
              />
            </fieldset>
          )}
        </>
      )}

      {form.reason === "wrong_category" && (
        <>
          {context.category && (
            <div className="mt-4">
              <span className={LABEL}>Filed under now</span>
              <div className="rounded-control border border-line bg-ground px-3 py-2.5 text-sm">
                {context.category}
              </div>
            </div>
          )}
          <div className="mt-4">
            <label htmlFor="report-category" className={LABEL}>
              Where should it be? <span className={OPTIONAL}>(optional)</span>
            </label>
            <input
              id="report-category"
              name="category"
              autoComplete="off"
              maxLength={200}
              placeholder="e.g. Motor drivers"
              value={form.category}
              onChange={(event) => patch({ category: event.target.value })}
              className={INPUT}
            />
          </div>
        </>
      )}

      {form.reason === "wrong_details" && (
        <>
          <fieldset
            className="mt-4"
            aria-describedby={errors.detailField ? "report-err-detailField" : undefined}
          >
            <legend className={LABEL}>What’s wrong?</legend>
            <Chips
              name="detailField"
              options={DETAIL_FIELDS}
              value={form.detailField}
              onChange={(detailField) => {
                patch({ detailField });
                clearError("detailField");
              }}
            />
            <FieldError id="report-err-detailField" message={errors.detailField} />
          </fieldset>
          {shops.length > 1 && (
            <div className="mt-4">
              <label htmlFor="report-detail-shop" className={LABEL}>
                From which shop’s listing? <span className={OPTIONAL}>(optional)</span>
              </label>
              <select
                id="report-detail-shop"
                name="detailShop"
                value={form.detailShop}
                onChange={(event) => patch({ detailShop: event.target.value })}
                aria-describedby="report-detail-shop-hint"
                className={INPUT}
              >
                <option value="">Not sure</option>
                {shops.map((shop) => (
                  <option key={shop.slug} value={shop.slug}>
                    {shop.name}
                  </option>
                ))}
              </select>
              <p id="report-detail-shop-hint" className={cn(HINT, "mt-1.5 mb-0")}>
                Each shop’s panel under “What the shops say” is its own text.
              </p>
            </div>
          )}
        </>
      )}

      {form.reason === "shop_contact" && (
        <>
          {shops.length > 1 && (
            <div className="mt-4">
              <label htmlFor="report-contact-shop" className={LABEL}>
                Which shop?
              </label>
              <select
                id="report-contact-shop"
                name="contactShop"
                value={form.contactShop}
                aria-invalid={errors.contactShop ? true : undefined}
                aria-describedby={errors.contactShop ? "report-err-contactShop" : undefined}
                onChange={(event) => {
                  patch({ contactShop: event.target.value });
                  clearError("contactShop");
                }}
                className={INPUT}
              >
                <option value="">Choose a shop</option>
                {shops.map((shop) => (
                  <option key={shop.slug} value={shop.slug}>
                    {shop.name}
                  </option>
                ))}
              </select>
              <FieldError id="report-err-contactShop" message={errors.contactShop} />
            </div>
          )}
          <fieldset
            className="mt-4"
            aria-describedby={errors.contactField ? "report-err-contactField" : undefined}
          >
            <legend className={LABEL}>Which detail?</legend>
            <Chips
              name="contactField"
              options={CONTACT_FIELDS}
              value={form.contactField}
              onChange={(contactField) => {
                patch({ contactField });
                clearError("contactField");
              }}
            />
            <FieldError id="report-err-contactField" message={errors.contactField} />
          </fieldset>
        </>
      )}

      <div className="mt-4">
        <label htmlFor="report-description" className={LABEL}>
          {required ? "What’s wrong?" : "Anything else we should know?"}{" "}
          <span className={OPTIONAL}>{required ? "(required)" : "(optional)"}</span>
        </label>
        <textarea
          id="report-description"
          name="description"
          maxLength={MAX_DESCRIPTION}
          required={required}
          value={form.description}
          onChange={(event) => {
            patch({ description: event.target.value });
            clearError("description");
          }}
          aria-invalid={errors.description ? true : undefined}
          aria-describedby={described(
            "report-description-count",
            errors.description && "report-err-description",
          )}
          placeholder={
            required ? "Tell us what you noticed" : "e.g. One of them is the 4.5A version"
          }
          className={cn(INPUT, "min-h-26 resize-y leading-[1.45]")}
        />
        <div id="report-description-count" className="mt-1 text-right text-xs text-ink-3 tabular">
          {form.description.length.toLocaleString("en-US")} /{" "}
          {MAX_DESCRIPTION.toLocaleString("en-US")}
        </div>
        <FieldError id="report-err-description" message={errors.description} />
      </div>

      <div className="mt-4">
        <label htmlFor="report-email" className={LABEL}>
          Email <span className={OPTIONAL}>(optional)</span>
        </label>
        <input
          id="report-email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          spellCheck={false}
          maxLength={254}
          value={form.email}
          onChange={(event) => {
            patch({ email: event.target.value });
            clearError("email");
          }}
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={described("report-email-hint", errors.email && "report-err-email")}
          className={INPUT}
        />
        <p id="report-email-hint" className={cn(HINT, "mt-1.5 mb-0")}>
          Only to reply to you about this report.
        </p>
        <FieldError id="report-err-email" message={errors.email} />
      </div>

      {/* The honeypot: off-screen, out of the tab order and hidden from
          screen readers, so only something filling every field fills it. */}
      <div aria-hidden="true" className="absolute -left-[10000px] h-px w-px overflow-hidden">
        <label htmlFor="report-website">Website</label>
        <input
          id="report-website"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          value={form.website}
          onChange={(event) => patch({ website: event.target.value })}
        />
      </div>

      <p data-report-privacy className="mt-4 text-[12.5px] leading-[1.45] text-ink-2">
        We use your report to correct this page and to improve how makhzan matches products. An
        email is used only to reply, and deleted 90 days after you send it. To stop spam we keep a
        scrambled form of your IP address for 24 hours.{" "}
        <Link href={routes.privacy()} target="_blank" className="text-link underline">
          Privacy policy<span className="sr-only"> (opens in a new tab)</span>
        </Link>
      </p>
    </>
  );
}

type Candidate = PickedProduct;

/**
 * "Which product is it the same as?": a search of makhzan as you type, or a
 * pasted product link. An ARIA combobox: Down and Up move through the list,
 * Enter picks, Esc closes the list (and only the list).
 */
function ProductPicker({
  context,
  picked,
  error,
  onListOpen,
  onPick,
}: {
  context: ReportContext;
  picked: PickedProduct | null;
  error?: string;
  onListOpen: (open: boolean) => void;
  onPick: (product: PickedProduct | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Candidate[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const change = useRef<HTMLButtonElement>(null);
  const focusAfter = useRef<"input" | "change" | null>(null);
  const id = useId();

  const pending = useRef<{ timer?: ReturnType<typeof setTimeout>; controller?: AbortController }>(
    {},
  );

  useEffect(() => {
    onListOpen(expanded);
  }, [expanded, onListOpen]);
  useEffect(
    () => () => {
      onListOpen(false);
      clearTimeout(pending.current.timer);
      pending.current.controller?.abort();
    },
    [onListOpen],
  );

  useEffect(() => {
    const target = focusAfter.current;
    focusAfter.current = null;
    if (target === "input") input.current?.focus();
    if (target === "change") change.current?.focus();
  });

  /** Search as the visitor types, a moment after they stop; the last search wins. */
  const search = (text: string) => {
    clearTimeout(pending.current.timer);
    pending.current.controller?.abort();
    const q = text.trim();
    if (q.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    pending.current.controller = controller;
    setLoading(true);
    pending.current.timer = setTimeout(async () => {
      const found = await findProducts(q, context.productId, controller.signal);
      if (controller.signal.aborted) return;
      setResults(found);
      setActive(-1);
      setLoading(false);
    }, 200);
  };

  const pick = (candidate: Candidate) => {
    setExpanded(false);
    setActive(-1);
    focusAfter.current = "change";
    onPick(candidate);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (results.length === 0) return;
      setExpanded(true);
      setActive((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (results.length === 0) return;
      setExpanded(true);
      setActive((i) => (i - 1 + results.length) % results.length);
    } else if (event.key === "Enter") {
      if (expanded && active >= 0 && results[active]) {
        event.preventDefault();
        pick(results[active]);
      }
    } else if (event.key === "Escape" && expanded) {
      event.preventDefault();
      event.stopPropagation();
      setExpanded(false);
      setActive(-1);
      // The dialog hears this Esc too, and must still find the list open:
      // the effect that tells it the list closed runs after this event.
    }
  };

  const listId = `${id}-list`;
  const status = !expanded
    ? ""
    : loading
      ? "Searching…"
      : results.length
        ? `${results.length} product${results.length === 1 ? "" : "s"} found`
        : "No products match";

  return (
    <div className="mt-4">
      <label htmlFor="report-other" className={LABEL}>
        Which product is it the same as?
      </label>
      <p id="report-other-hint" className={HINT}>
        Search makhzan, or paste the other product’s link.
      </p>
      {picked ? (
        <div
          data-report-picked
          className="flex items-center gap-2.5 rounded-control border-[1.5px] border-link p-2.5"
        >
          <span className="min-w-0 flex-1">
            <b dir="auto" className="block text-sm font-semibold">
              {picked.title}
            </b>
            <span className="text-[12.5px] text-ink-2">{picked.meta}</span>
          </span>
          <button
            ref={change}
            type="button"
            aria-label="Change the other product"
            onClick={() => {
              focusAfter.current = "input";
              onPick(null);
              setExpanded(query.trim().length >= 2);
            }}
            className="min-h-11 px-1.5 text-sm font-semibold text-link underline underline-offset-2"
          >
            Change
          </button>
        </div>
      ) : (
        <>
          <div className="relative">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-3 left-3 size-[18px] text-ink-3"
            />
            <input
              ref={input}
              id="report-other"
              data-report-combo
              type="text"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={expanded}
              aria-controls={listId}
              aria-activedescendant={expanded && active >= 0 ? `${id}-opt-${active}` : undefined}
              aria-describedby={error ? "report-other-hint report-err-other" : "report-other-hint"}
              aria-invalid={error ? true : undefined}
              autoComplete="off"
              placeholder="e.g. a part number"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                search(event.target.value);
                setExpanded(event.target.value.trim().length >= 2);
                setActive(-1);
              }}
              onKeyDown={onKeyDown}
              onBlur={() =>
                setTimeout(() => {
                  if (document.activeElement !== input.current) {
                    setExpanded(false);
                    setActive(-1);
                  }
                }, 120)
              }
              className={cn(INPUT, "ps-10")}
            />
          </div>
          <ul
            id={listId}
            role="listbox"
            aria-label="Matching products"
            hidden={!expanded}
            className="mt-1.5 rounded-control border border-line-strong bg-surface p-1"
          >
            {!loading && results.length === 0 && (
              <li role="presentation" className="p-2 text-[13px] text-ink-2">
                No products match. Try the part number, or paste its link.
              </li>
            )}
            {results.map((candidate, i) => (
              <li
                key={candidate.id}
                id={`${id}-opt-${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(candidate);
                }}
                className={cn(
                  "flex min-h-14 cursor-pointer flex-col justify-center rounded-md px-2 py-1.5 hover:bg-ground",
                  i === active && "bg-ground outline-[1.5px] -outline-offset-[1.5px] outline-link",
                )}
              >
                <b dir="auto" className="text-sm leading-tight font-medium">
                  {candidate.title}
                </b>
                <span className="text-[12.5px] text-ink-2">
                  {candidate.meta}
                  {candidate.partNumber && (
                    <>
                      {" · "}
                      <span data-identifier>{candidate.partNumber}</span>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <p aria-live="polite" className="sr-only">
            {status}
          </p>
        </>
      )}
      <FieldError id="report-err-other" message={error} />
    </div>
  );
}

type Hit = {
  id: string;
  title_en: string | null;
  title_ar: string | null;
  part_number: string | null;
  supplier_count: number;
  supplier_name?: string | null;
  min_price: number | null;
  max_price: number | null;
  currency: string;
};

function candidateFrom(hit: Hit): Candidate {
  const priced = hit.min_price !== null || hit.max_price !== null;
  return {
    id: hit.id,
    title: hit.title_en || hit.title_ar || hit.part_number || "Untitled product",
    partNumber: hit.part_number,
    meta: candidateMeta(
      hit.supplier_count,
      priced ? formatPriceRange(hit.min_price, hit.max_price, hit.currency) : null,
      hit.supplier_name,
    ),
  };
}

async function getJson<T>(path: string, signal: AbortSignal): Promise<T | null> {
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      signal,
      headers: { accept: "application/json" },
    });
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}

/** Products matching what was typed, or the one a pasted link names; never this one. */
async function findProducts(
  query: string,
  self: string,
  signal: AbortSignal,
): Promise<Candidate[]> {
  const linked = productIdFromLink(query);
  if (linked) {
    let product = await getJson<Hit>(`/products/${encodeURIComponent(linked)}`, signal);
    if (!product) {
      const moved = await getJson<{ id: string }>(
        `/products/${encodeURIComponent(linked)}/redirect`,
        signal,
      );
      if (moved) product = await getJson<Hit>(`/products/${encodeURIComponent(moved.id)}`, signal);
    }
    return product && product.id !== self ? [candidateFrom(product)] : [];
  }
  const found = await getJson<{ hits: Hit[] }>(
    `/search?${new URLSearchParams({ q: query, limit: "6" })}`,
    signal,
  );
  return (found?.hits ?? []).filter((hit) => hit.id !== self).map(candidateFrom);
}

function Sent({
  heading,
  matching,
  email,
  reference,
  sentAt,
}: {
  heading: React.RefObject<HTMLHeadingElement | null>;
  matching: boolean;
  email: string;
  reference: string | null;
  sentAt: Date | null;
}) {
  return (
    <div role="status" data-report-sent className="pt-2 pb-1">
      <div className="mb-3 grid size-11 place-items-center rounded-full border-[1.5px] border-line-strong text-ink">
        <Check aria-hidden="true" className="size-[22px]" />
      </div>
      <h3 ref={heading} tabIndex={-1} className="mb-1.5 text-xl outline-none">
        Thanks — we review every report
      </h3>
      <p className="mb-2 text-sm text-ink-2">
        A person reads each one. If it’s right, we correct the page
        {matching ? " and teach makhzan’s matching not to repeat it" : ""}.
      </p>
      <p className="mb-2 text-sm text-ink-2">
        {email ? (
          <>
            We’ll reply to <b className="text-ink">{email}</b> when it’s done.
          </>
        ) : (
          "You didn’t leave an email, so we won’t be able to tell you when it’s fixed."
        )}
      </p>
      {reference && (
        <p data-report-reference className="text-[13px] text-ink-3">
          Report {reference}
          {sentAt &&
            ` · ${sentAt.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`}
        </p>
      )}
    </div>
  );
}
