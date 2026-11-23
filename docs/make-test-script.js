// To regenerate the Word file: npm install docx@9.5.1 in an empty folder, copy this file there,
// then run: node make-test-script.js QC-Lab-End-to-End-Test-Script.docx  (kept here so a reboot cannot lose it)
// QC Lab end-to-end test script, as a Word file. Usage: node make.js <out.docx>
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  HeadingLevel, AlignmentType, LevelFormat, Footer, PageNumber, BorderStyle, TableLayoutType,
} = require("docx");

const FONT = "Calibri";
const CODE = "Consolas";
const INK = "1F2937";
const QUIET = "6B7280";
const BRAND = "0F6E6E";
const CONTENT_W = 9638; // A4 with 2 cm margins

// **bold** and `code` inside a line
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), font: CODE, size: 19, color: "374151", ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const para = (text, opts = {}) => new Paragraph({ children: runs(text), spacing: { after: 120 }, ...opts });
const heading = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)],
  spacing: { before: 360, after: 140 } });

const border = { style: BorderStyle.SINGLE, size: 4, color: "D1D5DB" };
const borders = { top: border, bottom: border, left: border, right: border };

function table(widths, header, rows) {
  const cell = (text, w, head) => new TableCell({
    width: { size: w, type: WidthType.DXA },
    borders,
    shading: head ? { type: ShadingType.CLEAR, color: "auto", fill: "E6F2F2" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: runs(text, head ? { bold: true, color: BRAND } : {}) })],
  });
  return new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((t, i) => cell(t, widths[i], false)) })),
    ],
  });
}

// One part: a lead, numbered steps, each with its detail lines and "Expect:" lines.
let partNo = 0;
const numberingConfigs = [];
function part(title, lead, steps, note) {
  partNo += 1;
  const ref = `steps-${partNo}`;
  numberingConfigs.push({
    reference: ref,
    levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 400, hanging: 400 } } } },
      { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 800, hanging: 300 } } } },
    ],
  });
  const out = [heading(title), para(lead)];
  for (const [head, ...subs] of steps) {
    out.push(new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(head), spacing: { before: 100, after: 60 } }));
    for (const s of subs) {
      const expect = s.startsWith("Expect");
      out.push(new Paragraph({
        numbering: { reference: ref, level: 1 },
        children: expect ? [new TextRun({ text: "Expect: ", bold: true, color: BRAND }), ...runs(s.replace(/^Expect[^:]*:\s*/, ""))] : runs(s),
        spacing: { after: 40 },
      }));
      if (expect && s.match(/^Expect, (.*?):/)) {
        // "Expect, signed in as X:" keeps its qualifier
        out.pop();
        const q = s.match(/^Expect, (.*?):\s*(.*)$/);
        out.push(new Paragraph({
          numbering: { reference: ref, level: 1 },
          children: [new TextRun({ text: `Expect, ${q[1].replace(/`/g, "")}: `, bold: true, color: BRAND }), ...runs(q[2])],
          spacing: { after: 40 },
        }));
      }
    }
  }
  if (note) out.push(para(note, { spacing: { before: 160, after: 120 } }));
  return out;
}

const body = [
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("QC Lab — End-to-end test script")], spacing: { after: 80 } }),
  new Paragraph({ children: [new TextRun({ text: "19-Nov-2026", color: QUIET })], spacing: { after: 240 } }),

  heading("Before you start"),
  para("You need the app open at http://localhost:5173 and eight logins. Every login below uses the password `qclab1234`, and all eight are listed on the sign-in page."),
  table([2700, 1900, 2538, 2500], ["Person in this test", "Username", "Name in the app", "Used in"], [
    ["Administrator", "`sysadmin`", "System Admin", "Parts 1 and 8"],
    ["Front desk (sample custodian)", "`frontdesk`", "Farah Iqbal", "Parts 2 and 4"],
    ["Production operator", "`prod.operator`", "Kamran Ali", "Part 3"],
    ["Production supervisor", "`prod.officer`", "Asif Mehmood", "Parts 3 and 8"],
    ["Analyst", "`analyst.gf`", "Ahmed Raza", "Part 5"],
    ["Checker", "`checker`", "Bilal Ahmed", "Part 6"],
    ["QA officer", "`qa.officer`", "Usman Tariq", "Parts 6 and 7"],
    ["Lab head", "`labhead`", "Dr. Nadia Hussain", "Parts 6 and 7"],
  ]),
  new Paragraph({ children: [], spacing: { after: 80 } }),
  ...[
    "**One window per person.** A browser window holds one sign-in. To keep two or three people signed in at once, use a normal window, a private window and a second browser.",
    "**Sessions end after 15 idle minutes.** Having to sign in again is expected, not a fault.",
    "**Name test data clearly.** Nothing in QC Lab is ever deleted. Use the names in this script (product `TST-500`, batch `TEST-B001`) so test records are easy to tell apart later.",
    "**Record as you go.** Each step says what you should see. Mark it in the Results log at the end, with a note on anything different.",
    "**Messages appear at the top right.** Green when something is saved, red when the server refuses it. A red one names what to fix, and that field is outlined in red until you change it.",
    "**Testing from a second computer** (optional): on the same network, open `http://<this computer's address>:5173`. Run `ipconfig` on this computer and use the IPv4 Address under Wi-Fi. The address can change when the Wi-Fi changes.",
  ].map((t) => new Paragraph({ numbering: { reference: "tips", level: 0 }, children: runs(t), spacing: { after: 60 } })),

  ...part("Part 1 — Set up a product",
    "You create product `TST-500` and give it a specification. You put it on the Extended review workflow (Checked → QA review → Approved). You give it two batch-record stages, one of them signed by QA.",
    [
      ["**Create the product** — `sysadmin`.",
        "Admin → Products → **+ New product**.",
        "Product code `TST-500`, section General Formulation, product name `Test Tablets 500 mg`.",
        "Dosage form Tablet, strength 500 mg, shelf life 24 months. Save.",
        "Expect: `TST-500` is in the list, and its specification and QC stages cells show **Set up**."],
      ["**Choose its review workflow** — `sysadmin`.",
        "Admin → Workflows → open **Extended review**.",
        "Check its chain reads Analysed → Checked (Checker) → QA review (QA officer) → Approved (Lab head).",
        "In the **Products** table at the bottom, set `TST-500` to Extended review.",
        "Expect: the Signatures column for `TST-500` shows 4."],
      ["**Draft the specification** — `sysadmin`.",
        "Admin → Products → click **Set up** in the specification cell of `TST-500`.",
        "Under **Product specification**, click **Set up the specification**.",
        "Click **+ Add a test** three times: Description (text, expected “Complies”, limit “White, round tablets”); Assay (range 95.0 to 105.0 %); Disintegration (maximum 15 min).",
        "Click **Create draft**.",
        "Expect: the draft shows, and it says nothing is in force yet. Copy this page's address for the next step."],
      ["**Make it effective** — `labhead`, in a second window.",
        "Open the address you copied, then click **Make effective…** and sign with the password.",
        "Expect: the specification shows as version 1, made effective by Dr. Nadia Hussain. Samples of `TST-500` can now be registered."],
      ["**Add the QC stages** — `sysadmin`, on the same product page. Click **Set up stages**, then build two stages.",
        "**Stage 1, Bulking** — batch record, required for release. Step “Dry mixing” with check points Mixing time (start and end time) and Blend weight in kg (number, limits 98 to 102). Step “Granulation” with LOD (percentage, limits 2.0 to 4.0). Sign-off columns: Done by (Production operator), Checked by (Production supervisor). Where they are signed: **Under every step**.",
        "**Stage 2, Compression** — batch record, required for release. One step, “Compression”, with Average weight in mg (number, limits 495 to 505) and Appearance (choice: Complies is acceptable, Does not comply is not). Sign-off columns: Done by (Production operator), Checked by (Production supervisor), Verified by QA (**QA officer**). Where they are signed: **Once for the stage**.",
        "Give the reason “Test script set-up” and save.",
        "Expect: two stages, version 1. The QA column on Compression is how a stage is handed to QA."],
      ["**See how stages are copied** (optional, nothing is saved) — `sysadmin`, on the same product page.",
        "Click **Change stages**, then **Copy stages from another product**, and choose `FLX-500 · Floxcip 500 mg Tablets`.",
        "Click **View** on Bulking (Lot-A).",
        "Expect: Floxcip's batch-record stages as cards, three to a row. A note says its 2 lab-tested stages are not offered for now. View opens the stage across the window: each step with its check points, kind of value and limit, then the sign-off columns in signing order (Done by → Checked by (Production) → Checked by (QA)).",
        "Click **Cancel** in the window, then **Cancel** under the stages.",
        "Expect: `TST-500` still has its two stages, version 1. Copying is how a new product starts from one already set up."],
    ],
    "New stages can only be batch records for now: “Tested in the lab” and “QA pass / fail” are hidden as choices at the lab's request. So the release sample in Part 4 is registered for the batch without a stage."),

  ...part("Part 2 — Create the batch",
    "The batch copies the product's stages when it is created, so do this only after Part 1.",
    [
      ["**Create it** — `frontdesk`.",
        "Batches → **+ New batch**.",
        "Product `TST-500`, official batch number `TEST-B001`, manufactured today, expiry two years from today. Click **Create batch**.",
        "Expect: the batch is listed with an internal ID such as `BATCH-000008` and QC stages **0 of 2 passed**."],
      ["**Try a duplicate** — `frontdesk`. Create `TEST-B001` for `TST-500` again.",
        "Expect: refused, naming the batch that already exists."],
      ["**Open the batch** — click its row.",
        "Expect: Bulking and Compression are listed with their steps, check points and sign-off columns, each marked “Not assigned: anyone who fills batch records can do it”. There is a **Print** group with Label and Batch record."],
      ["**Production can see it** — `prod.operator`, in another window. Open Batches.",
        "Expect: `TEST-B001` is listed. The menu has no All samples: production sees batches, not the lab's samples."],
    ]),

  ...part("Part 3 — Production fills the batch record",
    "The production supervisor assigns each stage to the person who fills it. Once one stage of a batch is assigned, the batch works by assignment: everyone still sees every stage, but a stage is filled only by the person it is assigned to. Production enters the values on the batch page and signs each column. QA signs its own column on Compression. Every signature asks for the signer's password.",
    [
      ["**Assign Bulking** — `prod.officer`. On `TEST-B001`, under Bulking, click **Assign…**.",
        "Choose Kamran Ali, type the note “Day shift” and click **Assign**.",
        "Expect: the window warns that this is the first stage of the batch to be assigned. Bulking then shows “Assigned to Kamran Ali · by Asif Mehmood” with the time and note. Compression shows **Not assigned yet**: it waits for the supervisor to name who does it."],
      ["**An unassigned stage waits** — `prod.operator`. Look at Compression.",
        "Expect: its check points are read-only, with no boxes to type in, and it says Compression is not assigned to anyone yet: the production supervisor names who does it."],
      ["**Only the assignee fills Bulking** — `prod.officer`. Look at Bulking.",
        "Expect: its check points are read-only for him too, saying Bulking is assigned to Kamran Ali and only they write its values. He still sees every stage and value, and can sign his own Checked by columns later."],
      ["**Kamran's tasks** — `prod.operator`. Open **My tasks**.",
        "Expect: a tile “Batch records assigned to you” showing 1, and the item “1. Bulking” with how many values are still to write, assigned by Asif Mehmood with the note. The sample tiles are not shown to production.",
        "Click **Open the stage →**.",
        "Expect: the batch opens at Bulking, which is marked “Assigned to you”."],
      ["**Fill Dry mixing** — `prod.operator`.",
        "Under Bulking → Dry mixing, press **Now** for the start and the end of mixing.",
        "Enter Blend weight `100.5`, then click **Save this step**.",
        "Expect: saved, with no flag. A green message at the top right says what was saved."],
      ["**Change a saved value** — `prod.operator`. Change Blend weight to `100.8` and click **Save this step** without giving a reason.",
        "Expect: a red **Not saved** message. Under Blend weight, the old value shows as “Was …” above the box **Why change it? (required)**, which is outlined in red with the cursor in it. Nothing is saved.",
        "Type “Re-weighed on the calibrated balance” and save.",
        "Expect: 100.8 is the current value. 100.5 stays in its history, with the reason."],
      ["**Enter a value out of limits** — `prod.operator`. Under Granulation, enter LOD `4.6` (the limit is 2.0 to 4.0) and save without a reason.",
        "Expect: the value is flagged Out of limit, and the box “Why is it outside the limit?” is outlined in red. Give “Drying extended, rechecked” and save."],
      ["**Sign Done by on Dry mixing** — `prod.operator`.",
        "Expect: the step is locked. Changing Blend weight now is refused, because the step's values are final."],
      ["**Sign a second column yourself** — `prod.operator`. Try Checked by on Dry mixing.",
        "Expect: refused, because one person signs only one column of a step."],
      ["**Check Dry mixing** — `prod.officer`. Sign Checked by on Dry mixing."],
      ["**Finish Granulation** — `prod.operator` signs Done by, then `prod.officer` signs Checked by.",
        "Expect: before signing the last column, the supervisor is asked to acknowledge the out-of-limit LOD. Bulking then shows as passed, and it leaves Kamran's My tasks once he has signed Done by on both steps."],
      ["**Assign Compression** — `prod.officer`. Under Compression, click **Assign…**, choose Kamran Ali and click **Assign**.",
        "Expect: Compression shows “Assigned to Kamran Ali”, and it appears in Kamran's My tasks. **Assignment history** on a stage lists every assignment, newest first."],
      ["**Fill and sign Compression** — `prod.operator` enters Average weight `500.2` and Appearance Complies, saves, and signs Done by. Then `prod.officer` signs Checked by.",
        "Expect: the stage waits for the QA column."],
      ["**QA verifies** — `qa.officer`. Open `TEST-B001` and sign Verified by QA on Compression.",
        "Expect: Compression passes and the batch shows **2 of 2 passed**. Anyone without the QA officer role is refused when they try to sign that column."],
      ["**Print the batch record** — any of them. Click **Batch record** in the Print group.",
        "Expect: a printable record with every value, the flag and reason on LOD, and each signature with name and time."],
    ]),

  ...part("Part 4 — Receive the sample",
    "The front desk records the release sample of `TEST-B001`. The sample is tested against the specification now in force. The front desk assigns it to an analyst trained for the section.",
    [
      ["**Register it** — `frontdesk`. Open **Receive samples** and fill in:",
        "Section General Formulation, product `TST-500`, from a batch, batch `TEST-B001`.",
        "Quantity `60 tablets`, received from Production, due date three days from today, analyst **Ahmed Raza**. Click Register.",
        "Expect: the batch details fill in automatically once the batch number matches. No QC stage is asked for, because the batch has no lab-tested stage. A sample number such as `GF-2026-0005` is issued."],
      ["**Only trained analysts are offered** — `frontdesk`. Open the analyst list again.",
        "Expect: only analysts trained for General Formulation are listed. Sana Khan (API section) is not."],
      ["**Print the label** — on the sample page, click **Label** in the Print group.",
        "Expect: a label with the sample number, product and batch, in a new tab."],
      ["**Reassign and back** (optional) — `frontdesk`. On the sample page, reassign it to Hina Malik, then back to Ahmed Raza.",
        "Expect: both moves are in the sample's history, with who did them and when."],
      ["**See it on the batch** — open `TEST-B001`.",
        "Expect: the batch lists 1 sample, not yet approved."],
    ]),

  ...part("Part 5 — The analyst tests it",
    "The analyst enters each result against its limit and corrects one with a reason. Signing as Analysed by builds the certificate and sends it for review.",
    [
      ["**Find the work** — `analyst.gf`. Open **My worklist**.",
        "Expect: the new sample is listed with its due date. If the screen shows checklist items for the sample, tick them as you go."],
      ["**Enter the results** — open the sample. Enter Description `Complies`, Assay `99.0`, Disintegration `8`.",
        "Expect: each shows as a pass against its limit (95.0 to 105.0 %, at most 15 min)."],
      ["**Correct a value** — change Assay to `99.5`, with the reason “Transcription error, worksheet p. 12”.",
        "Expect: 99.5 is the current value. 99.0 stays in the result's history with who changed it, when and why."],
      ["**Another analyst cannot enter results** — `analyst.gf2`. Try to open the same sample.",
        "Expect: they cannot open the sample or enter results, because it is assigned to Ahmed Raza."],
      ["**Sign as Analysed by** — `analyst.gf`. Click **✎ Sign as “Analysed by”** and give the password.",
        "Expect: the certificate is built and frozen, and the sample moves to review, waiting on Checked. Results can no longer be changed."],
    ],
    "Test a failing result separately, on a sample of its own. A failure starts the out-of-specification process (investigation, retest authorization). It holds the certificate and the batch until the investigation is closed."),

  ...part("Part 6 — Review: checker, QA, lab head",
    "The certificate passes Checked, QA review and Approved in that order, each signed by a different person. QA sends it back once, so you also test the correction loop.",
    [
      ["**Checked** — `checker`. Open **Awaiting my signature**, then the sample. Read the results against the limits and sign with the password.",
        "Expect: the sample moves on to QA review. The checker is not offered the QA review or Approved signature."],
      ["**QA sends it back** — `qa.officer`. Open **Awaiting my signature**, then the sample, then click **Send back…** with the comment “Add the worksheet reference”.",
        "Expect: refused if there is no comment. With the comment, the sample returns to the analyst, who is notified, and this certificate version is superseded."],
      ["**Correct and sign again** — `analyst.gf`. Open the sample, add the worksheet reference `WS-TST-001` in the raw data, and sign as Analysed by again.",
        "Expect: certificate version 2, which needs every signature again. The earlier Checked signature does not carry over."],
      ["**Checked again, then QA review** — `checker` signs, then `qa.officer` signs QA review.",
        "Expect: the sample now waits on Approved."],
      ["**Approve** — `labhead`. Open **Awaiting my signature**, then the sample, and approve with the password.",
        "Expect: the sample is Approved and the certificate is in force. It shows Analysed by, Checked by, QA review and Approved by, each with a name and time."],
      ["**Print the certificate** — `frontdesk`. Open the certificate and print it twice.",
        "Expect: the first print is copy 1, the original. The second is marked as a numbered duplicate. Scanning the QR code opens the verification page."],
    ]),

  ...part("Part 7 — Release the batch",
    "The lab head releases `TEST-B001` once both stages have passed and its sample is approved. Until then, the release is refused with the reasons.",
    [
      ["**The guard** — `labhead`. Do this before Part 6 step 5, while the sample is still in review.",
        "On `TEST-B001`, open **Disposition**, click **Decide…** and choose Released.",
        "Expect: refused, naming the sample that is not approved yet."],
      ["**Release it** — `labhead`, after Part 6.",
        "Open **Disposition**, click **Decide…**, choose Released.",
        "Give the reason “All stages passed, certificate in force”, enter the password and click **Record decision**.",
        "Expect: the batch shows Released, with who decided and when. The Batches list shows it too."],
      ["**No second release** — `labhead`. Try Released again.",
        "Expect: refused, because the batch is already released."],
      ["**Not for production** — `prod.officer`. Open `TEST-B001`.",
        "Expect: the disposition is shown, but there is no Decide button."],
      ["**The summary** — `labhead`. Reports → Batch QC Summary → `TEST-B001`.",
        "Expect: its sample, tests, certificate, both stages passed and the release decision, all on one page."],
      ["**The audit trail** — `sysadmin`. Admin → Activity log, search for `TEST-B001`.",
        "Expect: every step of Parts 2 to 7, each with the person and the time."],
    ]),

  ...part("Part 8 — Access and settings",
    "These checks narrow what one role, or the whole lab, can see, then put it back. Each change asks for a reason and is recorded.",
    [
      ["**One report only** — `sysadmin`.",
        "Admin → Roles → Production supervisor.",
        "Tick **Open reports**. Under “Reports this role opens”, tick only **Batch QC Summary**. Save with a reason.",
        "Expect, signed in as `prod.officer`: the menu shows Reports, containing Batch QC Summary and nothing else. Sample and product names in it show as plain text, not links. Opening another report's address is refused."],
      ["**No Lab records** — `sysadmin`. On the same role, untick every “See …” box under Lab records and save.",
        "Expect, signed in as `prod.officer`: Lab records is gone from the menu. On the Checker role, “See instruments” stays ticked and can't be unticked, because the checker manages instruments."],
      ["**Hide a feature for everyone** — `sysadmin`. Admin → Settings → **Features shown**, switch off OOT Trends.",
        "Expect: OOT Trends is gone from Reports for every login, `sysadmin` included. On the Roles screen it is marked “hidden in Settings”. **Show everything** brings it back."],
      ["**Who is signed in** — `sysadmin`, with two or three other people signed in. Open Admin → **Sign-in and sessions**.",
        "Expect: one row per computer, marked online or idle, with the browser, address and sign-in time.",
        "**Sign out…** on another person's row sends that window to the sign-in page. Their account is untouched."],
      ["**Lockout** — type a wrong password five times for `checker`. Then, as `sysadmin`, open Sign-in and sessions.",
        "Expect: Locked out shows 1, and the checker's row says Locked out with an **Unlock** button.",
        "After Unlock, the checker can sign in at once. Recent sign-ins lists the wrong passwords, the lockout and the unlock."],
      ["**What you can do** — any login. Open **My account**.",
        "Expect: the person's permissions grouped by area in plain words, with the reports as tags. No technical keys."],
      ["**Who may assign stages** — `sysadmin`. Admin → Roles → Production supervisor, under Production.",
        "Expect: **Assign batch-record stages** is ticked. On Production operator it is not, so in Part 3 Kamran had no Assign… button. Ticking it on another role lets that role assign too."],
      ["**Put it back** — `sysadmin`. On Production supervisor, untick Open reports and Batch QC Summary, and tick its Lab records boxes again.",
        "Expect: `prod.officer` sees what they saw before Part 8."],
    ]),

  heading("Results log"),
  para("Fill in each step's result as you go: Not run, Pass, Fail or Blocked. A Fail or Blocked needs a note saying what you saw instead, and the sample or batch number."),
  table([700, 4138, 1300, 1500, 2000], ["Step", "What is checked", "Result", "Tested by", "Notes"], [
    ["1.1", "Product TST-500 created"], ["1.2", "TST-500 on Extended review"], ["1.3", "Specification drafted"],
    ["1.4", "Lab head makes it effective"], ["1.5", "Two batch-record stages, QA column on Compression"],
    ["1.6", "Copy stages: View shows steps, limits, sign-offs (optional)"],
    ["2.1", "Batch TEST-B001 created, 0 of 2 passed"], ["2.2", "Duplicate batch refused"],
    ["2.3", "Batch page shows stages, Not assigned, and Print"], ["2.4", "Production sees the batch, not samples"],
    ["3.1", "Bulking assigned to Kamran; first-assignment warning"], ["3.2", "Unassigned Compression is read-only"],
    ["3.3", "Assigned Bulking is read-only for others"], ["3.4", "My tasks lists Bulking; link opens it"],
    ["3.5", "Dry mixing values saved, green message"], ["3.6", "Change needs a reason: box outlined, red message"],
    ["3.7", "Out-of-limit LOD needs a reason"], ["3.8", "Signed step is locked"],
    ["3.9", "One person signs one column"], ["3.10", "Supervisor signs Dry mixing"],
    ["3.11", "Out-of-limit acknowledged, Bulking passes, leaves My tasks"], ["3.12", "Compression assigned, in My tasks"],
    ["3.13", "Compression waits for QA"], ["3.14", "QA verifies, 2 of 2 passed"], ["3.15", "Batch record prints"],
    ["4.1", "Sample registered without a stage"], ["4.2", "Only trained analysts offered"], ["4.3", "Label prints"],
    ["4.4", "Reassign and back (optional)"], ["4.5", "Batch lists the sample"],
    ["5.1", "Sample on the worklist"], ["5.2", "Results pass their limits"], ["5.3", "Correction kept with its reason"],
    ["5.4", "Other analyst cannot enter"], ["5.5", "Signed as Analysed by"],
    ["6.1", "Checker signs"], ["6.2", "QA sends back with a comment"], ["6.3", "Version 2 needs every signature"],
    ["6.4", "Checked and QA review signed"], ["6.5", "Lab head approves"], ["6.6", "Certificate copy 1, then a duplicate"],
    ["7.1", "Release refused while in review"], ["7.2", "Batch released"], ["7.3", "Second release refused"],
    ["7.4", "No Decide for production"], ["7.5", "Batch QC Summary shows it all"], ["7.6", "Activity log shows every step"],
    ["8.1", "One report only for a role"], ["8.2", "No Lab records for a role"],
    ["8.3", "Feature hidden for everyone, then shown"], ["8.4", "Sessions listed; one signed out"],
    ["8.5", "Lockout and Unlock"], ["8.6", "What you can do, grouped"],
    ["8.7", "Assign batch-record stages on the supervisor only"], ["8.8", "Role put back"],
  ].map(([step, what]) => [step, what, "", "", ""])),
];

const doc = new Document({
  creator: "QC Lab",
  title: "QC Lab — End-to-end test script",
  styles: {
    default: { document: { run: { font: FONT, size: 21, color: INK } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { font: FONT, size: 40, bold: true, color: BRAND } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 28, bold: true, color: BRAND }, paragraph: { keepNext: true } },
    ],
  },
  numbering: {
    config: [
      { reference: "tips", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 400, hanging: 300 } } } }] },
      ...numberingConfigs,
    ],
  },
  sections: [{
    properties: { page: { margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
    footers: {
      default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
        new TextRun({ text: "QC Lab — End-to-end test script   ·   Page ", color: QUIET, size: 16 }),
        new TextRun({ children: [PageNumber.CURRENT], color: QUIET, size: 16 }),
        new TextRun({ text: " of ", color: QUIET, size: 16 }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], color: QUIET, size: 16 }),
      ] })] }),
    },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2], buf);
  console.log("wrote", process.argv[2], buf.length, "bytes");
});
