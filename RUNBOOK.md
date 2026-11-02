# Monday refresh – GitHub version

This repository is the LBC weekly bookings page (GitHub Pages: index.html reads data/*.csv).
The Monday scheduled task refreshes the data from Ticket Tailor and commits it to main.

## Steps (run from the repository root)
1. Make a work folder outside the repo, e.g. /tmp/wk, with series/, orders/, voided/. Copy refresh/refresh.py and refresh/history.json into it.
2. Series list: Ticket Tailor event_series_get with created_at_gte = (today − 450 days, Unix seconds), limit 100. Save each page as series/pN.json (if a result is saved to a tool-results file, copy that file). Page with starting_after = id of the last series until links.next is null.
3. `python3 refresh.py select YYYY-MM-DD` → selected.json.
4. For each selected series SID (read-only calls only):
   - orders_get(event_series_id=SID, limit=100), paging with starting_after; save page k to orders/SID_pk.json; then write the page count to orders/SID.odone.
   - issued_tickets_get(event_series_id=SID, status="voided", limit=100), same paging, voided/SID_pk.json and voided/SID.vdone.
   With 15+ series, split fetching across 2–3 subagents.
5. `python3 refresh.py build YYYY-MM-DD` → upcoming_<date>.csv, booking_curves_<date>.csv, health_<date>.csv, updated history.json.
   CHECKS: DIFF on a single-occurrence series means places don't match Ticket Tailor's issued count. Investigate; if it can't be explained, don't publish – report it.
6. Copy into the repo: upcoming_<date>.csv → data/upcoming.csv, booking_curves_<date>.csv → data/curves.csv, health_<date>.csv → data/health.csv, history.json → refresh/history.json.
7. Commit with message "Bookings refresh <date>" and push to main. Don't change index.html.
8. Summary for Bodhimati: date, ahead/behind/on track, new bookings this week, anything odd.

## Rules (agreed with Bodhimati)
Places: ticket lines only, order not cancelled, ticket ID present and not voided; coach seats separate. Retreats = Vajrasana series + Adhisthana Winter Retreat (split All 10 / First 5 / Last 5 days); deposit and Final/Balance Payment series combined by start date. Excluded: ROWE / Regional Order Weekend, ordination, Buddha Day, tests, coach-only, TEAM, one-off workshops. Courses = LBC multi-week courses (14+ days), one occurrence = one run. Past runs = last three of the same type. "Coming up next" = next non-Intro course and next 4+ night non-winter retreat. Pace = booked now vs the past runs at the same days before start. Occupancy = places ÷ beds on retreats finished in the last 12 weeks; heading-for = predicted places ÷ beds for the next 12 weeks. Demand = places booked in the last 4 weeks ÷ what past runs booked over the same stretch. New this week = places booked in the last 7 days.
