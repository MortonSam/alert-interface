# Backlog

Items agreed with Sam, not yet built. Each entry names the rule and the surfaces it touches; building one is its own block.

- **Large acquisitions hold the P/E whatever the payment form.** Today the P/E rule holds a window (status `not_meaningful_yet`) for a spin-off, merger, share-exchange acquisition or rename-merge; a cash acquisition is classified `other` and recorded nowhere. Rule to build: any acquisition whose value exceeds 25% of the acquirer's market value at announcement holds the P/E for four clean quarters regardless of payment form (cash, stock or mixed), with the deal's 8-K as the receipt. Needs the deal value read from the filing or stored by hand, the acquirer's market value on the announcement date from the stored bars and shares outstanding, and a `record_corporate_action` kind for it. Added 2026-10-07.
