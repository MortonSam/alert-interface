"""Every visitor-facing word the accounts backend sends: API messages and the emails' fixed text (Claude's drafts, 2026-10-29, for
Sam's approval; nothing here is shown while ACCOUNTS_ENABLED is off). The frontend's screens are in frontend/src/lib/accountCopy.ts.
Both are listed verbatim in backend/ops/reports/accounts_2026-10-29/wording.md (built from these modules), and a test
holds every string here to the email rules: no buy, sell or what-to-do language, no urgency words.
"""
from __future__ import annotations

SENDER_NAME = "Ivy at Alert Interface"
NO_CALLS = "Ivy doesn't make buy or sell calls."

API = {
    "link_sent": "If that address can receive email, a sign-in link is on its way. It works once, for 15 minutes.",
    "link_invalid": "That doesn't look like an email address.",
    "link_limited": "Too many sign-in links were asked for in the last few minutes. Try again a little later.",
    "link_used": "This sign-in link was already used. Ask for a new one.",
    "link_expired": "This sign-in link has expired. Ask for a new one.",
    "link_unknown": "This sign-in link isn't valid. Ask for a new one.",
    "signed_out": "You're signed out.",
    "signed_out_everywhere": "You're signed out on every device.",
    "deleted": "Your account and everything saved to it are deleted.",
    "unsubscribed": "You won't get the {kind} email any more. You can turn it back on in your settings.",
    "unsubscribed_all": "You won't get any email from Ivy any more. You can turn each one back on in your settings.",
    "unsubscribe_bad": "This unsubscribe link isn't valid. You can change every email in your settings.",
    "sign_in_needed": "Sign in to use this. Reading stays open to everyone.",
    "email_suppressed": "Emails to this address bounced or were reported as spam, so Ivy has stopped sending them. To get them again, write to sam@alertinterface.com from this address.",
}

KINDS = {   # every email type, all off until the person turns one on
    "date_confirmed": {"name": "Date confirmed", "about": "When a stock you follow confirms its report date: the date, the time, and what options price for it."},
    "earnings_eve": {"name": "Earnings eve", "about": "The evening before a stock you follow reports: Ivy's Read, its typical report move and the confirmed time."},
    "morning_after": {"name": "Morning after", "about": "The day after a stock you follow reports: how much it moved against what options priced, and your hypothetical trades on it that expired."},
    "earnings_week": {"name": "Sunday earnings week", "about": "Sunday evening: the week's ten largest companies reporting, and the stocks you follow that report that week."},
}

def offered_kinds(sunday_on: bool) -> dict:
    """Pure: the email types a person can turn on: every kind but the Sunday earnings week while SUNDAY_EMAIL_ENABLED is off."""
    return {k: v for k, v in KINDS.items() if k != "earnings_week" or sunday_on}


SIGN_IN_EMAIL = {
    "subject": "Your sign-in link for Alert Interface",
    "lead": "Here is your link to sign in to Alert Interface.",
    "button": "Sign in",
    "note": "It works once, for 15 minutes. If you didn't ask for it, you can ignore this email and nothing changes.",
}

EMAIL = {
    "subject_one": "{title}",
    "subject_many": "{first} and {n} more from Ivy",
    "greeting": "Here's what changed for the stocks you follow.",
    "open_page": "Open the {name} page",
    "footer_why": "You get this because you turned on {kinds} in your settings.",
    "footer_unsubscribe": "Unsubscribe from this email",
    "footer_unsubscribe_all": "Unsubscribe from these emails",
    "footer_settings": "Email settings",
    "footer_one_a_day": "Ivy sends at most one email a day.",
    # a. date confirmed
    "confirmed_title": "{name} confirmed its report date",
    "confirmed_line": "{name} reports on {day}{timing}, a date the company has confirmed.",
    # like with like (Sam, 2026-11-03, the walkthrough's rule): the report's own share of the move against the typical report-day move,
    # or the options figure with its expiration and no comparison
    "confirmed_options": "Options price a move of about ±{report}% from the report itself, {cmp} its typical ±{typical}% on a report day.",
    "confirmed_options_term": "Options price a move of about ±{implied}% by {expiration}, the first expiration after the report.",
    "confirmed_typical": "After its past {n} reports, it moved ±{typical}% on a typical report day.",
    # b. earnings eve
    "eve_title": "{name} reports {when}",
    "eve_line": "{name} reports {when}{timing}, a date the company has confirmed.",
    "eve_read_lead": "Ivy's Read",
    "eve_typical": "After its past {n} reports, it moved ±{typical}% on a typical report day.",
    # c. morning after
    "after_title": "How {name} moved after its report",
    "after_move": "{name} {moved} on {day}, the first session after its report.",
    "after_vs_priced": "Options had priced a move of about ±{implied}% from the report itself, so it moved {cmp} options priced.",
    "after_history": "In {k} of its last {n} reports on file, it moved more than options priced.",
    "after_trades_lead": "Your hypothetical trades on {name} that expired",
    "after_trade": "{label}, saved {saved}: cost {cost}, worth {worth} at expiration, {result}.",
    "hypothetical": "Hypothetical, never a real trade.",
    # d. Sunday earnings week
    "week_title": "This week's earnings, {start} to {end}",
    "week_lead": "The ten largest companies reporting this week",
    "week_line": "{name} reports on {day}{timing}.",
    "week_yours": "Stocks you follow that report this week",
}
TIMING = {"bmo": ", before the market opens", "amc": ", after the market closes"}
COMPARE = {"more than usual": "more than", "less than usual": "less than", "about its usual": "about the same as"}
MOVED_VS = {"more": "more than", "less": "less than", "same": "about as much as"}
