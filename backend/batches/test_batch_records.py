"""
Batch records: a recorded stage's steps, check points and sign-off columns, set on
the product; filled on the shop floor and signed in order, by role, with values out
of limit flagged, explained and acknowledged.
"""
from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from accounts.models import Role, User
from audit.describe import describe
from audit.models import AuditEvent
from certificates.tests import PW
from .models import BatchCheckpointEntry, BatchStageSignature, QcCheckpoint, QcSignoff, QcStep
from .services import disposition_basis, release_problems
from .test_stage_refinements import RefinedBase


def yesterday(hour, minute=0):
    day = timezone.localdate() - timedelta(days=1)
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}"


class RecordBase(RefinedBase):
    def setUp(self):
        super().setUp()
        self.op_role = Role.objects.get(code="PRODUCTION_OPERATOR")
        self.sup_role = Role.objects.get(code="PRODUCTION_SUPERVISOR")
        self.operator = User.objects.create_user(username="operator", password=PW, role=self.op_role,
                                                 first_name="Operator")
        self.supervisor = User.objects.create_user(username="supervisor", password=PW, role=self.sup_role,
                                                   first_name="Supervisor")

    def bulking(self, signoffs=None, **extra):
        return {
            "name": "Bulking (Lot-C)", "kind": "RECORDED", "required": True, **extra,
            "steps": [
                {"title": "Premixing", "instructions": "a) Clean the Sigma Mixer thoroughly and dry it.",
                 "checkpoints": [
                     {"label": "Ciprofloxacin HCl", "kind": "NUMBER", "unit": "kg", "decimals": 3},
                     {"label": "Mixing", "kind": "TIME_RANGE"},
                 ]},
                {"title": "Drying", "instructions": "c) Dry the granules till LOD achieves 3.00–4.50 %.",
                 "checkpoints": [
                     {"label": "LOD", "kind": "PERCENT", "min_value": "3.00", "max_value": "4.50", "decimals": 2},
                     {"label": "Remarks", "kind": "TEXT", "required": False},
                 ]},
            ],
            "signoffs": signoffs if signoffs is not None else [
                {"title": "Done by", "holder": "Operator", "role_id": self.op_role.id},
                {"title": "Checked by", "holder": "Production", "role_id": self.sup_role.id},
                {"title": "Checked by", "holder": "QA", "role_id": self.roles["APPROVER"].id},
            ],
        }

    def batch_with(self, *stages):
        ids = self.set_up_stages(list(stages))
        return self.new_batch(), ids

    def points(self, batch_id, stage="Bulking (Lot-C)"):
        st = self.stage(batch_id, stage)
        return {cp["label"]: cp for step in st["record"]["steps"] for cp in step["checkpoints"]}

    def write(self, batch_id, stage_id, entries, user=None):
        self.login(user or self.operator)
        return self.client.post(f"/api/batches/{batch_id}/qc-stages/{stage_id}/entries/", {"entries": entries},
                                format="json")

    def sign(self, batch_id, stage_id, signoff_id, user, password=PW, **extra):
        self.login(user)
        return self.client.post(f"/api/batches/{batch_id}/qc-stages/{stage_id}/sign/",
                                {"signoff_id": signoff_id, "password": password, **extra}, format="json")

    def fill_all(self, batch, sid, lod="3.80", reason=""):
        p = self.points(batch.id)
        r = self.write(batch.id, sid, [
            {"checkpoint_id": p["Ciprofloxacin HCl"]["id"], "number": "17.887"},
            {"checkpoint_id": p["Mixing"]["id"], "start": yesterday(10, 10), "end": yesterday(10, 30)},
            {"checkpoint_id": p["LOD"]["id"], "number": lod, "reason": reason},
        ])
        self.assertEqual(r.status_code, 200, r.content)

    def columns(self, batch_id, stage="Bulking (Lot-C)"):
        return self.stage(batch_id, stage)["record"]["signoffs"]


class TemplateTests(RecordBase):
    def test_a_recorded_stage_keeps_its_steps_check_points_and_sign_offs(self):
        self.set_up_stages([self.bulking()])
        self.login(self.admin)
        data = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data
        stage = data["current"]["stages"][0]
        self.assertEqual([s["title"] for s in stage["steps"]], ["Premixing", "Drying"])
        lod = stage["steps"][1]["checkpoints"][0]
        self.assertEqual((lod["kind"], lod["unit"], lod["limit_text"]), ("PERCENT", "%", "3.00 – 4.50 %"))
        self.assertEqual([(s["title"], s["holder"], s["role"]) for s in stage["signoffs"]],
                         [("Done by", "Operator", "Production operator"),
                          ("Checked by", "Production", "Production supervisor"),
                          ("Checked by", "QA", "Lab head (QCM / HOD)")])
        self.assertIn("Production operator", [r["name"] for r in data["roles"]])
        self.assertEqual((QcStep.objects.count(), QcCheckpoint.objects.count(), QcSignoff.objects.count()), (2, 4, 3))
        # Saved again unchanged, it makes no new version.
        r = self.put_stages([self.bulking()], reason="")
        self.assertEqual(r.data["current"]["version"], 1)
        event = AuditEvent.objects.get(action="QC_STAGES_CHANGED")
        self.assertIn("2 steps, 4 check points, 3 sign-offs", event.details["stages"][0])

    def test_a_bad_template_is_refused_in_plain_words(self):
        good = self.bulking()
        for change, words in (
            ({"signoffs": []}, "at least one sign-off column"),
            ({"steps": [{"title": " ", "checkpoints": []}]}, "needs a title"),
            ({"steps": [{"title": "Drying", "checkpoints": [{"label": "LOD", "kind": "PERCENT", "min_value": "5",
                                                              "max_value": "3"}]}]}, "above its upper limit"),
            ({"steps": [{"title": "Drying", "checkpoints": [{"label": "LOD", "kind": "PERCENT"},
                                                             {"label": "lod", "kind": "NUMBER"}]}]}, "two check points"),
            ({"steps": [{"title": "Drying", "checkpoints": [{"label": "LOD", "kind": "WEIGHT"}]}]}, "what kind of value"),
            ({"signoffs": [{"title": "Done by", "role_id": 99999}]}, "Choose the role"),
        ):
            r = self.put_stages([{**good, **change}])
            self.assertEqual(r.status_code, 400, change)
            self.assertIn(words, r.data["detail"])

    def test_a_stage_tested_in_the_lab_has_no_steps(self):
        self.set_up_stages([{**self.bulking(), "kind": "TESTED"}])
        self.assertFalse(QcStep.objects.exists())


class FillingTests(RecordBase):
    def test_production_fills_the_record_and_the_stage_is_under_way(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        self.assertEqual(self.status_of(batch.id, "Bulking (Lot-C)"), "NOT_STARTED")
        self.fill_all(batch, sid)
        p = self.points(batch.id)
        self.assertEqual(p["Ciprofloxacin HCl"]["entry"]["shown"], "17.887 kg")
        self.assertEqual(p["LOD"]["entry"]["out_of_limit"], False)
        self.assertEqual(self.status_of(batch.id, "Bulking (Lot-C)"), "IN_PROGRESS")
        event = AuditEvent.objects.get(action="BATCH_RECORD_WRITTEN")
        self.assertIn("Ciprofloxacin HCl 17.887 kg", describe(event)["sentence"])

    def test_production_sees_every_batch_but_not_the_labs_samples(self):
        batch, _ = self.batch_with(self.bulking())
        self.register_sample()
        self.login(self.operator)
        self.assertEqual([b["id"] for b in self.client.get("/api/batches/").data["results"]], [batch.id])
        self.assertEqual(self.client.get(f"/api/batches/{batch.id}/").status_code, 200)
        self.assertEqual(self.client.get("/api/samples/?status=ALL").data["count"], 0)

    def test_a_value_out_of_limit_needs_a_reason_and_is_flagged(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        lod = self.points(batch.id)["LOD"]["id"]
        r = self.write(batch.id, sid, [{"checkpoint_id": lod, "number": "5.10"}])
        self.refused(r, "outside its limit of 3.00 – 4.50 %")
        self.assertFalse(BatchCheckpointEntry.objects.exists())
        r = self.write(batch.id, sid, [{"checkpoint_id": lod, "number": "5.10", "reason": "Drier tripped for 10 min"}])
        self.assertEqual(r.status_code, 200, r.content)
        entry = self.points(batch.id)["LOD"]["entry"]
        self.assertEqual((entry["out_of_limit"], entry["reason"]), (True, "Drier tripped for 10 min"))

    def test_a_change_needs_a_reason_and_the_old_value_stays(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        api = self.points(batch.id)["Ciprofloxacin HCl"]["id"]
        self.write(batch.id, sid, [{"checkpoint_id": api, "number": "17.887"}])
        self.refused(self.write(batch.id, sid, [{"checkpoint_id": api, "number": "17.878"}]),
                     "already reads 17.887 kg. Say why")
        r = self.write(batch.id, sid, [{"checkpoint_id": api, "number": "17.878", "correction": "Digits swapped"}])
        self.assertEqual(r.status_code, 200, r.content)
        point = self.points(batch.id)["Ciprofloxacin HCl"]
        self.assertEqual((point["entry"]["shown"], point["entry"]["correction"]), ("17.878 kg", "Digits swapped"))
        self.assertEqual([h["shown"] for h in point["history"]], ["17.887 kg"])
        # The same value again is no change at all.
        self.write(batch.id, sid, [{"checkpoint_id": api, "number": "17.878"}])
        self.assertEqual(BatchCheckpointEntry.objects.count(), 2)

    def test_bad_values_are_refused_and_nothing_is_saved(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        p = self.points(batch.id)
        future = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        for entries, words in (
            ([{"checkpoint_id": p["Ciprofloxacin HCl"]["id"], "number": "seventeen"}], "must be a number"),
            ([{"checkpoint_id": p["Mixing"]["id"], "start": yesterday(10, 30), "end": yesterday(10, 10)}],
             "end time is before the start"),
            ([{"checkpoint_id": p["Mixing"]["id"], "start": yesterday(10)}], "both the start and the end"),
            ([{"checkpoint_id": p["Mixing"]["id"], "start": future, "end": future}], "cannot be in the future"),
            ([{"checkpoint_id": p["Ciprofloxacin HCl"]["id"], "number": "17.887"}, {"checkpoint_id": 999999,
                                                                                     "number": "1"}], "not one this stage"),
        ):
            self.refused(self.write(batch.id, sid, entries), words)
        self.assertFalse(BatchCheckpointEntry.objects.exists())

    def test_only_those_who_may_fill_the_record(self):
        batch, ids = self.batch_with(self.bulking())
        api = self.points(batch.id)["Ciprofloxacin HCl"]["id"]
        self.refused(self.write(batch.id, ids["Bulking (Lot-C)"], [{"checkpoint_id": api, "number": "1"}],
                                user=self.checker), "permission to fill batch records")


class SigningTests(RecordBase):
    def test_the_columns_are_signed_in_order_by_their_roles_and_the_stage_passes(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        done, prod, qa = (c["id"] for c in self.columns(batch.id))
        self.refused(self.sign(batch.id, sid, done, self.operator), "Fill every required value first")
        self.fill_all(batch, sid)
        self.refused(self.sign(batch.id, sid, prod, self.supervisor), "“Done by” is signed first")
        self.refused(self.sign(batch.id, sid, done, self.supervisor), "signed by Production operator")
        self.refused(self.sign(batch.id, sid, done, self.operator, password="wrong"), "Password incorrect")
        self.assertEqual(self.sign(batch.id, sid, done, self.operator).status_code, 200)
        # Once the first column is signed, the values are final.
        api = self.points(batch.id)["Ciprofloxacin HCl"]["id"]
        self.refused(self.write(batch.id, sid, [{"checkpoint_id": api, "number": "1", "correction": "x"}]),
                     "the values of this stage are final")
        self.assertEqual(self.sign(batch.id, sid, prod, self.supervisor).status_code, 200)
        self.assertEqual(self.status_of(batch.id, "Bulking (Lot-C)"), "IN_PROGRESS")
        self.assertEqual(self.sign(batch.id, sid, qa, self.approver).status_code, 200)
        self.assertEqual(self.status_of(batch.id, "Bulking (Lot-C)"), "PASSED")
        cols = self.columns(batch.id)
        self.assertEqual([c["signature"]["by"]["name"] for c in cols], ["Operator", "Supervisor", "Labhead"])
        self.assertEqual(len(disposition_basis(batch)["qc_stages"][0]["signatures"]), 3)
        sentences = [describe(e)["sentence"] for e in AuditEvent.objects.filter(action="BATCH_STAGE_SIGNED")]
        self.assertTrue(any("signed “Done by (Operator)” on stage “Bulking (Lot-C)”" in x for x in sentences), sentences)

    def test_one_person_signs_one_column_of_a_stage(self):
        two_by_supervisor = [
            {"title": "Done by", "holder": "Operator", "role_id": self.op_role.id},
            {"title": "Checked by", "holder": "Production", "role_id": self.sup_role.id},
            {"title": "Verified by", "holder": "Production", "role_id": self.sup_role.id},
        ]
        batch, ids = self.batch_with(self.bulking(signoffs=two_by_supervisor))
        sid = ids["Bulking (Lot-C)"]
        self.fill_all(batch, sid)
        done, checked, verified = (c["id"] for c in self.columns(batch.id))
        self.sign(batch.id, sid, done, self.operator)
        self.assertEqual(self.sign(batch.id, sid, checked, self.supervisor).status_code, 200)
        self.refused(self.sign(batch.id, sid, verified, self.supervisor), "someone else signs “Verified by”")

    def test_the_last_column_acknowledges_values_out_of_limit(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        self.fill_all(batch, sid, lod="5.10", reason="Drier tripped for 10 min")
        done, prod, qa = (c["id"] for c in self.columns(batch.id))
        self.sign(batch.id, sid, done, self.operator)
        self.sign(batch.id, sid, prod, self.supervisor)
        self.assertTrue(self.columns(batch.id)[2]["acknowledges"])
        self.refused(self.sign(batch.id, sid, qa, self.approver), "1 value is out of limit (LOD 5.10 %)")
        self.refused(self.sign(batch.id, sid, qa, self.approver, acknowledge=True), "with a comment")
        r = self.sign(batch.id, sid, qa, self.approver, acknowledge=True, comment="Re-dried; LOD 3.9 % on recheck")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(BatchStageSignature.objects.get(signoff_id=qa).acknowledged)
        self.assertEqual(self.status_of(batch.id, "Bulking (Lot-C)"), "PASSED")

    def test_an_optional_stage_with_a_value_out_of_limit_holds_release_until_acknowledged(self):
        batch, ids = self.batch_with(self.bulking(required=False))
        sid = ids["Bulking (Lot-C)"]
        lod = self.points(batch.id)["LOD"]["id"]
        self.write(batch.id, sid, [{"checkpoint_id": lod, "number": "5.10", "reason": "Drier tripped"}])
        self.assertTrue(any("out of limit that its last sign-off has not acknowledged" in p
                            for p in release_problems(batch)))

    def test_a_recorded_stage_without_sign_offs_is_still_recorded_passed_or_failed(self):
        batch, ids = self.batch_with({"name": "Line clearance", "kind": "RECORDED", "required": True},
                                     self.bulking())
        self.assertIsNone(self.stage(batch.id, "Line clearance")["record"])
        self.assertEqual(self.record(batch.id, ids["Line clearance"]).status_code, 200)
        self.refused(self.record(batch.id, ids["Bulking (Lot-C)"]), "filled and signed on the batch record")

    def test_a_stage_that_waits_takes_no_values_and_no_signatures(self):
        batch, ids = self.batch_with({"name": "Line clearance", "kind": "RECORDED", "required": True},
                                     self.bulking(after_previous=True))
        api = self.points(batch.id)["Ciprofloxacin HCl"]["id"]
        self.refused(self.write(batch.id, ids["Bulking (Lot-C)"], [{"checkpoint_id": api, "number": "1"}]),
                     "waits for the stages before it")
        self.assertIn("waits for the stages", self.columns(batch.id)[0]["blocked"])

    def test_not_applicable_only_before_anything_is_written(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        api = self.points(batch.id)["Ciprofloxacin HCl"]["id"]
        self.write(batch.id, sid, [{"checkpoint_id": api, "number": "17.887"}])
        self.refused(self.mark(batch.id, sid), "Only a stage nothing has been done for")

    def test_the_record_is_never_changed_in_the_database(self):
        if connection.vendor != "postgresql":
            self.skipTest("The locks are PostgreSQL triggers.")
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        self.fill_all(batch, sid)
        self.sign(batch.id, sid, self.columns(batch.id)[0]["id"], self.operator)
        entry, signature = BatchCheckpointEntry.objects.first(), BatchStageSignature.objects.get()
        for sql in (f"UPDATE batches_batchcheckpointentry SET number = 1 WHERE id = {entry.id}",
                    f"DELETE FROM batches_batchstagesignature WHERE id = {signature.id}",
                    f"UPDATE batches_qccheckpoint SET max_value = 99 WHERE id = {entry.checkpoint_id}"):
            with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql)


class ChoiceAndOwnKindTests(RecordBase):
    def visual(self, choices=None):
        stage = self.bulking()
        stage["steps"][1]["checkpoints"].append({
            "label": "Granule appearance", "kind": "CHOICE", "kind_name": "Complies / Does not comply",
            "choices": choices if choices is not None else [{"label": "Complies", "ok": True},
                                                            {"label": "Does not comply", "ok": False}],
        })
        return stage

    def test_a_choice_takes_one_of_its_options_and_flags_one_not_acceptable(self):
        batch, ids = self.batch_with(self.visual())
        sid = ids["Bulking (Lot-C)"]
        point = self.points(batch.id)["Granule appearance"]
        self.assertEqual((point["limit_text"], point["kind_name"]), ("Acceptable: Complies", "Complies / Does not comply"))
        self.refused(self.write(batch.id, sid, [{"checkpoint_id": point["id"], "text": "Maybe"}]), "choose one of its options")
        self.refused(self.write(batch.id, sid, [{"checkpoint_id": point["id"], "text": "does not comply"}]),
                     "not an acceptable answer (Acceptable: Complies)")
        r = self.write(batch.id, sid, [{"checkpoint_id": point["id"], "text": "does not comply", "reason": "Lumps seen"}])
        self.assertEqual(r.status_code, 200, r.content)
        entry = self.points(batch.id)["Granule appearance"]["entry"]
        self.assertEqual((entry["shown"], entry["out_of_limit"]), ("Does not comply", True))

    def test_a_choice_needs_options_and_an_acceptable_one(self):
        for choices, words in (([], "at least two options"), (["Only"], "at least two options"),
                               ([{"label": "A", "ok": False}, {"label": "B", "ok": False}], "as acceptable"),
                               (["Same", "same"], "twice")):
            r = self.put_stages([self.visual(choices)])
            self.assertEqual(r.status_code, 400, choices)
            self.assertIn(words, r.data["detail"])

    def test_the_lab_adds_its_own_kinds_and_every_stage_is_offered_them(self):
        self.login(self.admin)
        r = self.client.post("/api/checkpoint-kinds/", {"name": "Temperature", "kind": "NUMBER", "unit": "°C",
                                                         "min_value": "50", "max_value": "80", "decimals": 0},
                             format="json")
        self.assertEqual(r.status_code, 201, r.content)
        kind_id = r.data["id"]
        for body, words in (({"name": "temperature", "kind": "NUMBER"}, "already a kind"),
                            ({"name": "Percentage", "kind": "NUMBER"}, "already a built-in kind"),
                            ({"name": "Clean?", "kind": "CHOICE", "choices": ["Yes"]}, "at least two options")):
            r = self.client.post("/api/checkpoint-kinds/", body, format="json")
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(words, r.data["detail"])
        offered = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data["checkpoint_presets"]
        self.assertEqual([(k["name"], k["unit"], k["min_value"]) for k in offered], [("Temperature", "°C", "50")])
        # Retired, it is no longer offered; a stage that used it keeps its copy.
        self.put_stages([{**self.bulking(), "steps": [{"title": "Drying", "checkpoints": [
            {"label": "Inlet air", "kind": "NUMBER", "unit": "°C", "min_value": "50", "max_value": "80",
             "decimals": 0, "kind_name": "Temperature"}]}]}])
        self.assertEqual(self.client.patch(f"/api/checkpoint-kinds/{kind_id}/", {"is_active": False},
                                           format="json").status_code, 200)
        data = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data
        self.assertEqual(data["checkpoint_presets"], [])
        inlet = data["current"]["stages"][0]["steps"][0]["checkpoints"][0]
        self.assertEqual((inlet["kind_name"], inlet["limit_text"]), ("Temperature", "50 – 80 °C"))
        self.assertTrue(AuditEvent.objects.filter(action="CHECKPOINT_KIND_CREATED").exists())

    def test_only_those_who_manage_products_add_kinds(self):
        self.login(self.analyst)
        r = self.client.post("/api/checkpoint-kinds/", {"name": "Speed", "kind": "NUMBER"}, format="json")
        self.assertEqual(r.status_code, 403)


class VersionTests(RecordBase):
    def test_each_version_opens_as_it_was_with_what_it_changed(self):
        first = self.bulking()
        self.set_up_stages([first, GRAIN_STAGE])
        second = self.bulking()
        second["steps"][1]["checkpoints"][0]["max_value"] = "5.00"          # LOD limit widened
        second["steps"].append({"title": "Sizing", "checkpoints": []})       # a step added
        second["name"] = "Bulking (Lot-D)"                                   # renamed, same stage
        self.login(self.admin)
        current = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data["current"]["stages"]
        second["key"] = current[0]["key"]
        self.set_up_stages([second])                                         # Final grain removed
        v1 = self.client.get(f"/api/products/{self.product.id}/qc-stages/versions/1/").data
        v2 = self.client.get(f"/api/products/{self.product.id}/qc-stages/versions/2/").data
        self.assertEqual([s["name"] for s in v1["stages"]], ["Bulking (Lot-C)", "Final grain"])
        self.assertFalse(v1["is_current"])
        self.assertEqual(v1["changes"], ["First version: 2 stages."])
        self.assertTrue(v2["is_current"])
        for words in ("Renamed stage “Bulking (Lot-C)” to “Bulking (Lot-D)”.",
                      "“Bulking (Lot-D)” › Drying › LOD: limit 3.00 – 4.50 % → 3.00 – 5.00 %.",
                      "“Bulking (Lot-D)”: added step “Sizing”.",
                      "Removed stage “Final grain”."):
            self.assertIn(words, v2["changes"])
        event = AuditEvent.objects.filter(action="QC_STAGES_CHANGED").order_by("-id").first()
        self.assertIn("Removed stage “Final grain”.", event.details["changes"])
        self.assertEqual(self.client.get(f"/api/products/{self.product.id}/qc-stages/versions/9/").status_code, 404)


GRAIN_STAGE = {"name": "Final grain", "kind": "TESTED", "required": True}


class EveryStepTests(RecordBase):
    """A stage signed under every step, as the paper record has it: Date, Done by, Checked by."""

    def every_step(self, **extra):
        return self.bulking(sign_each_step=True, **extra)

    def steps(self, batch_id, stage="Bulking (Lot-C)"):
        return self.stage(batch_id, stage)["record"]["steps"]

    def step_columns(self, batch_id, n):
        return [c["id"] for c in self.steps(batch_id)[n]["signoffs"]]

    def test_each_step_is_signed_on_its_own_and_the_stage_passes_when_all_are(self):
        batch, ids = self.batch_with(self.every_step())
        sid = ids["Bulking (Lot-C)"]
        record = self.stage(batch.id, "Bulking (Lot-C)")["record"]
        self.assertTrue(record["per_step"])
        self.assertEqual(record["signoffs"], [])
        self.assertEqual([[c["title"] for c in st["signoffs"]] for st in record["steps"]],
                         [["Done by", "Checked by", "Checked by"]] * 2)
        p = self.points(batch.id)
        self.write(batch.id, sid, [
            {"checkpoint_id": p["Ciprofloxacin HCl"]["id"], "number": "17.887"},
            {"checkpoint_id": p["Mixing"]["id"], "start": yesterday(10, 10), "end": yesterday(10, 30)},
        ])
        (d1, p1, q1), (d2, p2, q2) = self.step_columns(batch.id, 0), self.step_columns(batch.id, 1)
        step1, step2 = (st["id"] for st in self.steps(batch.id))
        self.refused(self.sign(batch.id, sid, d1, self.operator), "Say which step is being signed")
        self.refused(self.sign(batch.id, sid, d2, self.operator, step_id=step2),
                     "Fill every required value of this step first: LOD")
        self.assertEqual(self.sign(batch.id, sid, d1, self.operator, step_id=step1).status_code, 200)
        # Step 1 is final; step 2 can still be written.
        self.refused(self.write(batch.id, sid, [{"checkpoint_id": p["Ciprofloxacin HCl"]["id"], "number": "1",
                                                 "correction": "x"}]), "Step 1, Premixing, has been signed")
        r = self.write(batch.id, sid, [{"checkpoint_id": p["LOD"]["id"], "number": "3.80"}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(self.steps(batch.id)[0]["locked"])
        self.assertFalse(self.steps(batch.id)[1]["locked"])
        self.refused(self.sign(batch.id, sid, q1, self.approver, step_id=step1), "“Checked by” is signed first")
        self.sign(batch.id, sid, p1, self.supervisor, step_id=step1)
        self.sign(batch.id, sid, q1, self.approver, step_id=step1)
        self.assertEqual(self.status_of(batch.id, "Bulking (Lot-C)"), "IN_PROGRESS")
        # The same operator signs Done by under the next step too.
        for col, who in ((d2, self.operator), (p2, self.supervisor), (q2, self.approver)):
            r = self.sign(batch.id, sid, col, who, step_id=step2)
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.status_of(batch.id, "Bulking (Lot-C)"), "PASSED")
        self.assertEqual([c["signature"]["by"]["name"] for c in self.steps(batch.id)[1]["signoffs"]],
                         ["Operator", "Supervisor", "Labhead"])
        self.assertEqual(len(disposition_basis(batch)["qc_stages"][0]["signatures"]), 6)
        self.assertEqual(BatchStageSignature.objects.filter(step__isnull=False).count(), 6)
        sentences = [describe(e)["sentence"] for e in AuditEvent.objects.filter(action="BATCH_STAGE_SIGNED")]
        self.assertTrue(any("Bulking (Lot-C), Step 2, Drying" in x for x in sentences), sentences)

    def test_one_person_signs_one_column_of_a_step(self):
        batch, ids = self.batch_with(self.every_step(signoffs=[
            {"title": "Done by", "holder": "Production", "role_id": self.sup_role.id},
            {"title": "Checked by", "holder": "Production", "role_id": self.sup_role.id},
        ]))
        sid = ids["Bulking (Lot-C)"]
        self.fill_all(batch, sid)
        step1 = self.steps(batch.id)[0]["id"]
        done, checked = self.step_columns(batch.id, 0)
        self.sign(batch.id, sid, done, self.supervisor, step_id=step1)
        self.refused(self.sign(batch.id, sid, checked, self.supervisor, step_id=step1),
                     "You signed “Done by” on this step")

    def test_the_last_column_of_a_step_acknowledges_that_steps_values_out_of_limit(self):
        batch, ids = self.batch_with(self.every_step(required=False))
        sid = ids["Bulking (Lot-C)"]
        self.fill_all(batch, sid, lod="5.10", reason="Drier tripped for 10 min")
        self.assertTrue(any("out of limit that its last sign-off has not acknowledged" in p
                            for p in release_problems(batch)))
        step1, step2 = (st["id"] for st in self.steps(batch.id))
        for n, step in ((0, step1), (1, step2)):
            done, prod, _ = self.step_columns(batch.id, n)
            self.sign(batch.id, sid, done, self.operator, step_id=step)
            self.sign(batch.id, sid, prod, self.supervisor, step_id=step)
        # Step 1 has nothing out of limit: QA signs it without acknowledging anything.
        q1 = self.step_columns(batch.id, 0)[2]
        self.assertEqual(self.sign(batch.id, sid, q1, self.approver, step_id=step1).status_code, 200)
        self.assertEqual(self.steps(batch.id)[1]["out_of_limit"][0]["label"], "LOD")
        q2 = self.step_columns(batch.id, 1)[2]
        self.refused(self.sign(batch.id, sid, q2, self.approver, step_id=step2), "1 value is out of limit (LOD 5.10 %)")
        r = self.sign(batch.id, sid, q2, self.approver, step_id=step2, acknowledge=True, comment="Re-dried; 3.9 %")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(list(BatchStageSignature.objects.filter(acknowledged=True).values_list("step__title", flat=True)),
                         ["Drying"])
        self.assertFalse(any("Bulking" in p for p in release_problems(batch)))

    def test_the_setting_is_part_of_the_version(self):
        self.set_up_stages([self.bulking()])
        self.login(self.admin)
        current = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data["current"]
        self.assertFalse(current["stages"][0]["sign_each_step"])
        before = self.new_batch()
        self.set_up_stages([self.every_step(key=current["stages"][0]["key"])])
        self.login(self.admin)
        v2 = self.client.get(f"/api/products/{self.product.id}/qc-stages/versions/2/").data
        self.assertTrue(v2["stages"][0]["sign_each_step"])
        self.assertIn("“Bulking (Lot-C)” is now signed at every step.", v2["changes"])
        # A batch keeps the version it was made with.
        self.assertFalse(self.stage(before.id, "Bulking (Lot-C)")["record"]["per_step"])
        self.assertTrue(self.stage(self.new_batch("B-002").id, "Bulking (Lot-C)")["record"]["per_step"])
        # A stage with no steps has nothing to sign step by step.
        self.set_up_stages([{"name": "Line clearance", "kind": "RECORDED", "required": True, "sign_each_step": True}])
        self.login(self.admin)
        self.assertFalse(self.client.get(f"/api/products/{self.product.id}/qc-stages/").data
                         ["current"]["stages"][0]["sign_each_step"])

    def test_a_stage_signed_once_takes_no_step(self):
        batch, ids = self.batch_with(self.bulking())
        sid = ids["Bulking (Lot-C)"]
        self.fill_all(batch, sid)
        done = self.columns(batch.id)[0]["id"]
        step1 = self.steps(batch.id)[0]["id"]
        self.refused(self.sign(batch.id, sid, done, self.operator, step_id=step1), "signed once for the whole stage")
