# DOEMS Alpha 7.3 — Release expired manual slots

Missed pending manual start windows now archive the closed plan and release the live slot. Existing faults whose reason is exactly manual_start_window_expired are recovered by the same path. Future plans, active plans, concepts and faults with other reasons are preserved.

The most recent expired manual plan per slot is stored durably outside the live plan as last_closed history and exposed as last_closed_plan on slot entities. It survives automatic refill and restart. Obsolete planning metadata remains in that history, not in the reusable slot. Failed saves roll back both live plans and history. Older storage without history remains compatible.

This corrects expiry handling; it does not establish the historical source of the October 6 record supplied by the user. Entity and unique-ID formulas remain unchanged. No physical execution authority or remote Home Assistant changes are introduced. Publication requires full Python 3.12 and 3.13 tests and package verification.
