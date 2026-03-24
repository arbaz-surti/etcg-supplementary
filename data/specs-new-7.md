# New Feature Specifications for Paper 2 Evaluation
# SPEC-19 through SPEC-25
# SPEC-19–22: De-identified from real QA tickets (restaurant technology domain)
# SPEC-23–25: Synthetic specs (healthcare, logistics × 2)

---

## SPEC-19

**Spec ID:** SPEC-19
**Domain:** Restaurant Technology
**Feature:** POS Main Panel Redesign — Beverage Size Buttons and Menu Panel Consolidation
**User Roles:** Team Member (order taker), Store Manager, Franchise Operator
**Description:** The point-of-sale system is being redesigned to improve transaction speed and ease of use by reducing the number of clicks, tabs, and screens required to complete an order. Key changes include the addition of size selection buttons (Small, Medium, Large) for beverages directly on the order entry screen, the relocation of Bakery and Beverage items from separate tabs to the main product panel, and an updated visual layout with a modernised design. The redesign is intended to surface approximately 90% of the menu mix on the main panel, eliminating the need for secondary navigation. No item repricing is required as part of this change.

**Acceptance Criteria:**
- AC1: Size selection buttons (S, M, L) appear on the order entry screen when a beverage item is selected and correctly modify the item price and description on the order ticket.
- AC2: Bakery items previously located in the Bakery tab are accessible directly from the main product panel without navigating to a secondary tab.
- AC3: Beverage items previously located in the Beverage tab are accessible directly from the main product panel without navigating to a secondary tab.
- AC4: The Beverage and Bakery tabs are no longer present in the POS navigation; selecting items from those categories does not require any tab interaction.
- AC5: The updated main panel layout reflects the new brand-forward visual design, including updated button colours, font sizes, and spacing as specified in the design brief.
- AC6: All existing item prices remain unchanged; no repricing is triggered by the panel reorganisation.
- AC7: Orders containing beverage items with size selections are transmitted correctly to the kitchen display and receipt printer with the correct size modifier and price.

**User Flows:**
1. Team member begins a new order, selects a beverage item from the main panel, taps the "M" (Medium) size button, and confirms the correct price modifier is applied to the order ticket.
2. Team member adds a bakery item from the main panel without navigating to a secondary tab, and the item appears on the order ticket correctly.
3. Team member completes a mixed order (beverage + bakery + food), tenders the transaction, and verifies that the kitchen display and receipt show all items with correct descriptions and prices.
4. Store manager reviews the main panel layout in the management console and confirms the redesigned panel matches the approved design configuration.

**Edge Cases / Notes:**
- If a beverage item does not support size selection (e.g., a fixed-size specialty drink), the S/M/L buttons should not appear or should be disabled for that item only.
- Verify that the removal of Bakery and Beverage tabs does not cause orphaned items (items that were only accessible via those tabs and are now unreachable).
- Test the redesign on all supported POS hardware form factors to confirm the layout renders correctly at different screen resolutions.

---

## SPEC-20

**Spec ID:** SPEC-20
**Domain:** Restaurant Technology
**Feature:** POS Workstation Network Endpoint Migration with Host File Override Testing
**User Roles:** QA Engineer, Network Administrator, Store Systems Administrator, Restaurant Operations Manager
**Description:** The POS system's production workstation is being migrated to a new network endpoint IP address for a key external service integration. The fully qualified domain name (FQDN) remains unchanged; only the underlying IP address is changing. To test this change safely before production deployment, the local host file on the POS workstation will be edited to redirect all outbound requests for the FQDN to the new IP address. Prior deployments of this type have caused issues in production. QA is required to validate that the endpoint change does not introduce posting delays, order storage failures, or labour management disruptions.

**Acceptance Criteria:**
- AC1: After the host file is updated to point the FQDN to the new IP address, the POS workstation successfully resolves the FQDN to the new endpoint without requiring a restart of the POS application.
- AC2: Transaction posting to the reporting and analytics system (R&A) occurs with no observable delay compared to baseline behaviour on the current endpoint.
- AC3: Orders are stored to the central order management system with no delay or failure after the endpoint change is applied.
- AC4: Labour management actions (clock-in, clock-out, job code changes) function correctly and are recorded accurately, confirming that the endpoint change does not disrupt the labour integration.
- AC5: No error messages or timeout warnings related to the FQDN or endpoint appear in the POS application logs during normal transaction flow.
- AC6: After the host file override is removed and the system reverts to DNS resolution, the POS workstation reconnects to the original endpoint without errors.

**User Flows:**
1. Network administrator edits the local host file on the test POS workstation to map the FQDN to the new IP address and confirms the change is saved correctly.
2. QA engineer completes a full transaction cycle (order entry, payment, receipt) and verifies that the posting to the R&A system occurs without delay.
3. QA engineer stores an order and confirms it appears in the order management system within the expected time window.
4. Team member clocks in using the POS, performs a job code change, and clocks out. QA engineer confirms all three labour events are recorded correctly in the labour system.
5. Network administrator removes the host file override. QA engineer completes another transaction and confirms the system returns to normal operation on the original endpoint.

**Edge Cases / Notes:**
- If the POS application caches the previous IP address, a DNS cache flush or application restart may be required; document whether this step is needed.
- Test on all POS workstation models in the test environment, as different hardware configurations may resolve DNS or cache connections differently.
- Verify behaviour when the new endpoint is temporarily unreachable (simulate by briefly blocking the IP) to confirm the POS fails gracefully rather than hanging indefinitely.

---

## SPEC-21

**Spec ID:** SPEC-21
**Domain:** Restaurant Technology
**Feature:** Non-Traditional Store Configuration — Single POS with Multiple Serial Printers
**User Roles:** Store Systems Administrator, Team Member, Service Technician, QA Engineer
**Description:** A new non-traditional store concept operates without a kitchen display system (KDS) and uses a single POS terminal connected to four serial printers serving distinct order routing purposes. The printers are connected via COM port serial connections and require specific port-to-printer role assignments: COM1 handles in-store order cup labels, COM2 handles above-store (aggregator/online) order cup labels, COM3 handles customer receipts, and COM5 handles on-the-go (OTG) order tickets. COM5 requires a physical RJ45-to-RJ12 adapter. The configuration must be validated to ensure that all print jobs route to the correct printer under all order types.

**Acceptance Criteria:**
- AC1: In-store orders print the cup label to the printer connected on COM1 and the customer receipt to the printer connected on COM3.
- AC2: Orders received from above-store channels (online ordering, third-party aggregators) print the cup label to the printer connected on COM2.
- AC3: On-the-go orders print the order ticket to the printer connected on COM5; the RJ45-to-RJ12 adapter is in place and the printer receives print jobs without errors.
- AC4: No cross-routing occurs: in-store orders do not trigger COM2 or COM5 printers, and above-store orders do not trigger COM1.
- AC5: If a printer on any COM port is offline or experiences a paper jam, the POS displays an appropriate error message and does not silently drop the print job.
- AC6: After a POS application restart or system reboot, all COM port-to-printer assignments are retained without requiring manual reconfiguration.
- AC7: The system functions correctly in the absence of a KDS; all order routing is handled exclusively through the serial printer configuration.

**User Flows:**
1. QA engineer places an in-store dine-in order on the POS and confirms the cup label prints on COM1 and the receipt prints on COM3; no output appears on COM2 or COM5.
2. A simulated above-store order is received via the online ordering integration; QA engineer confirms the cup label prints on COM2 and no label prints on COM1.
3. QA engineer places an on-the-go order and confirms the order ticket prints on COM5 via the RJ45-to-RJ12 adapter.
4. QA engineer disconnects the printer on COM3 (receipt printer) mid-shift, places an order, and confirms the POS displays a printer error rather than processing silently.
5. QA engineer reboots the POS and confirms all four COM port assignments are intact and print jobs route correctly on the first order after restart.

**Edge Cases / Notes:**
- Verify that the COM5 RJ45-to-RJ12 adapter does not introduce latency or intermittent connectivity; run a sustained print job batch to assess reliability.
- Test concurrent order scenarios (an in-store order and an above-store order arriving simultaneously) to confirm print jobs are queued correctly without cross-routing or dropped jobs.
- Confirm the configuration is stable after a POS software update, as update installers may reset peripheral configuration to defaults.

---

## SPEC-22

**Spec ID:** SPEC-22
**Domain:** Restaurant Technology
**Feature:** Loyalty Extension DLL Upgrade — Offline Transaction Retry Behaviour
**User Roles:** QA Engineer, Store Systems Administrator, Loyalty Integration Manager
**Description:** A new version of the loyalty extension dynamic-link library (DLL) has been released to address a defect in which the POS system continuously retries transactions it incorrectly classifies as offline. The defect occurs randomly in production and cannot be reliably reproduced in a test environment. The new DLL version corrects the retry logic. Since the defect cannot be directly reproduced, QA validation focuses on two objectives: confirming that the new DLL version functions at parity with the currently deployed version under normal operating conditions, and verifying that offline loyalty transactions are not subjected to continuous retry loops.

**Acceptance Criteria:**
- AC1: The new DLL version is deployed on the test POS and the correct version number is confirmed in the application logs and system configuration.
- AC2: Standard loyalty transactions (card swipe, QR code scan, phone number lookup) complete successfully and return the correct points balance and reward eligibility.
- AC3: Loyalty discounts and rewards are applied correctly to eligible orders and reflected on the customer receipt.
- AC4: When the POS is intentionally taken offline (network disconnected), loyalty transactions initiated in the offline state are queued and do not enter a continuous retry loop.
- AC5: When network connectivity is restored, queued offline loyalty transactions are processed once and not retried redundantly.
- AC6: The POS application does not exhibit performance degradation, freezing, or crash behaviour attributable to the new DLL version during a sustained transaction session (minimum 30 consecutive transactions).
- AC7: The loyalty extension log entries for offline transactions show a single retry attempt upon reconnection, not repeated attempts.

**User Flows:**
1. QA engineer confirms the new DLL version number in the system configuration and application log before beginning testing.
2. QA engineer completes 10 standard loyalty transactions (mix of card swipe, QR scan, and phone number lookup) and confirms all complete successfully with correct points and discount application.
3. QA engineer disconnects the network, initiates a loyalty transaction, and observes that the POS queues the transaction without entering a retry loop.
4. QA engineer reconnects the network and confirms the queued transaction is processed exactly once, with no duplicate or repeated retry entries in the log.
5. QA engineer runs a sustained session of 30+ transactions, including loyalty and non-loyalty orders, and confirms no performance issues or crashes occur.

**Edge Cases / Notes:**
- Since the original defect is non-reproducible, document the test environment configuration (network conditions, hardware model, POS version) to establish a baseline for future regression comparison.
- Verify the new DLL version is compatible with all loyalty provider transaction types in use (standard earn, redemption, comped transaction) — not just earn transactions.
- Test with an expired or invalid loyalty account to confirm the DLL handles error responses gracefully without entering an unintended retry state.

---

## SPEC-23

**Spec ID:** SPEC-23
**Domain:** Healthcare
**Feature:** Patient Portal — Lab Results Viewing and Secure Provider Messaging
**User Roles:** Patient, Primary Care Physician, Lab Technician, Portal Administrator
**Description:** A patient-facing web portal allows authenticated patients to view lab results released by their provider, download result PDFs, and send secure messages to their care team. Results are pulled from the hospital's Laboratory Information System via a FHIR integration. Providers control when results become visible to patients through a configurable release delay (default 72 hours after verification). Critical results trigger visual alerts and optional SMS/email notifications.

**Acceptance Criteria:**
- AC1: Verified lab results appear in the patient portal after the provider-configured release delay has elapsed.
- AC2: Patients can view individual result values with reference ranges and abnormal flags highlighted.
- AC3: Patients can download a PDF summary of any released lab panel.
- AC4: Patients can send a secure message to their care team directly from a lab result detail page, with the result automatically attached as context.
- AC5: Providers can override the release delay to publish results immediately or extend the hold period up to 14 days.
- AC6: Results marked as critical trigger a visual banner on the patient's dashboard and an optional SMS/email notification if the patient has opted in.
- AC7: Every result view, download, and message send is recorded with timestamp and user identity for audit purposes.

**User Flows:**
1. Patient logs into the portal, navigates to the Lab Results tab, and sees a chronological list of released results with status indicators (normal, abnormal, critical).
2. Patient selects a result panel, views individual values with reference ranges, and downloads a PDF copy.
3. Patient clicks Message My Provider from the result detail page, types a question, and submits; the message appears in the secure inbox with the lab result linked.
4. Lab technician marks a result as critical; after the release delay, the patient sees a critical banner on their dashboard.
5. Provider logs into the admin panel and overrides the release delay to publish a result immediately.

**Edge Cases / Notes:**
- If the FHIR sync fails mid-batch, partially synced results must not appear to the patient; the system should retry and display only complete panels.
- Patients with multiple providers should see results filtered by ordering provider.
- If a patient's SMS notification preference has an invalid phone number, the system should fall back to email and log the delivery failure.

---

## SPEC-24

**Spec ID:** SPEC-24
**Domain:** Logistics
**Feature:** Real-Time Shipment Tracking with Exception Alerting
**User Roles:** Shipper, Consignee, Dispatch Coordinator, Operations Manager
**Description:** A shipment tracking module provides real-time visibility into package location and status across the delivery lifecycle. GPS coordinates from driver devices are ingested every 60 seconds and displayed on an interactive map. Automated exception alerts (delay, damage report, failed delivery attempt) are pushed to shippers and consignees via configurable notification channels. The system integrates with multiple carrier APIs for multi-carrier shipments.

**Acceptance Criteria:**
- AC1: Shippers and consignees can look up shipment status by tracking number, order reference, or consignee name.
- AC2: The tracking detail page displays a timeline of status events with timestamps and location names.
- AC3: An interactive map shows the shipment's current GPS position, updated every 60 seconds while the driver's device is active.
- AC4: Exception events trigger automated notifications to the shipper and consignee within 5 minutes of the event.
- AC5: Dispatch coordinators can view all active shipments on a dashboard, filter by status, and drill down to individual tracking details.
- AC6: Multi-carrier shipments display a unified timeline that stitches events from multiple carrier APIs into a single view.
- AC7: Proof of delivery (signature or photo) appears on the tracking detail page within 10 minutes of delivery confirmation.

**User Flows:**
1. Consignee receives a shipping confirmation email with a tracking link and views the timeline showing pickup and in-transit status.
2. GPS updates show the package arriving at a regional hub; the timeline auto-updates with a hub scan event.
3. Driver reports a failed delivery attempt; the system creates an exception event, sends an SMS to the consignee, and notifies the shipper via webhook.
4. Dispatch coordinator filters the dashboard by exception status, identifies delayed shipments, and reassigns one to a different driver.
5. Driver completes delivery and captures a signature; proof of delivery appears on the consignee's tracking page within the SLA window.

**Edge Cases / Notes:**
- If GPS signal is lost for more than 10 minutes, the map should display the last known position with a stale-location indicator.
- Carrier API events may arrive out of order; the timeline must reorder events by event timestamp, not ingestion order.
- If a multi-carrier handoff event is missing, the system should infer the handoff from the receiving carrier's first scan and display an estimated qualifier.

---

## SPEC-25

**Spec ID:** SPEC-25
**Domain:** Logistics
**Feature:** Warehouse Inventory Management with Cycle Count Reconciliation
**User Roles:** Warehouse Associate, Inventory Manager, Receiving Clerk, Finance Auditor
**Description:** A warehouse inventory management system tracks stock levels across multiple bin locations using barcode scanning. The system supports receiving, putaway, picking, and shipping workflows. A cycle count module allows inventory managers to schedule partial physical counts by zone or SKU category and reconcile discrepancies against system-of-record quantities. Discrepancies exceeding a configurable threshold trigger an automatic hold on affected SKUs until resolved.

**Acceptance Criteria:**
- AC1: Receiving clerks can scan inbound shipment barcodes to log received quantities against purchase orders; over-receipts and short-receipts are flagged with reason codes.
- AC2: The system tracks inventory at the bin-location level, showing total warehouse quantity and a breakdown by bin per SKU.
- AC3: Inventory managers can create cycle count tasks by selecting a zone, aisle, or SKU category and assigning them to warehouse associates.
- AC4: Warehouse associates perform cycle counts by scanning bin barcodes and entering physical counts; the system calculates variance against system quantities in real time.
- AC5: Discrepancies exceeding the configurable threshold place the affected SKU in a count-hold state, preventing picks until an inventory manager resolves the variance.
- AC6: Inventory managers can resolve discrepancies by approving an adjustment, ordering a recount, or escalating to the finance auditor for write-off approval.
- AC7: All inventory adjustments are logged with timestamp, user, reason code, and before/after quantities for audit trail purposes.
- AC8: Finance auditors can generate a reconciliation report for any date range showing all adjustments, holds, and write-offs grouped by reason code.

**User Flows:**
1. Receiving clerk scans a pallet barcode at the dock, the system matches it to a purchase order, and the clerk confirms receipt with quantity and reason code for any discrepancy.
2. Inventory manager schedules a cycle count for a zone, assigns it to two warehouse associates, and sets a due date.
3. Warehouse associate scans a bin barcode and enters a physical count; the system calculates variance and triggers a count hold if the threshold is exceeded.
4. Inventory manager reviews the hold, identifies the cause (mis-shelved item), approves an adjustment, and releases the hold.
5. Finance auditor generates a monthly reconciliation report, reviews write-offs, and exports the report to the ERP system.

**Edge Cases / Notes:**
- If the handheld device loses connectivity mid-count, completed scans should be stored locally and synced on reconnect without creating duplicate records.
- A cycle count for a bin with active pick tasks in progress should warn the associate and offer to defer the count to avoid counting moving inventory.
- If an SKU has multiple units of measure, the cycle count interface must display and accept counts in the same UOM as the system record with a conversion option available.
