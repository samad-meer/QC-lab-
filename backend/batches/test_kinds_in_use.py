"""
The check point kinds page lists the kinds of value the products' current stages
already use, beside the lab's own kinds: check points that share a kind, unit,
limits and options are one row, with their names and where they are used.
"""
from .test_batch_records import RecordBase

OK_NOT_OK = [{"label": "OK", "ok": True}, {"label": "Not OK", "ok": False}]


class KindsInUseTests(RecordBase):
    def lubrication(self):
        return {
            "name": "Lubrication", "kind": "RECORDED", "required": True,
            "steps": [{"title": "Blending", "checkpoints": [
                {"label": "Magnesium  stearate", "kind": "NUMBER", "unit": "kg", "decimals": 3},
                {"label": "Area cleaned", "kind": "CHOICE", "choices": OK_NOT_OK},
                {"label": "Status board correct", "kind": "CHOICE", "choices": OK_NOT_OK},
                {"label": "Blend LOD", "kind": "PERCENT", "max_value": "2.0", "decimals": 1},
            ]}],
            "signoffs": [{"title": "Done by", "holder": "Operator", "role_id": self.op_role.id}],
        }

    def in_use(self, user=None):
        self.login(user or self.admin)
        return self.client.get("/api/checkpoint-kinds/in-use/")

    def test_shared_kinds_are_one_row_with_their_names_and_places(self):
        self.set_up_stages([self.bulking()])
        # A second version: only the version in force now is counted, not the first as well.
        self.set_up_stages([self.bulking(), self.lubrication()])
        r = self.in_use()
        self.assertEqual(r.status_code, 200, r.content)
        rows = {(g["kind"], g["unit"], g["min_value"], g["max_value"]): g for g in r.data}
        self.assertEqual(sum(g["uses"] for g in r.data), 8)

        weight = rows[("NUMBER", "kg", None, None)]
        self.assertEqual(weight["labels"], ["Ciprofloxacin HCl", "Magnesium stearate"])
        self.assertEqual(weight["uses"], 2)
        self.assertEqual([p["stage"] for p in weight["used_in"]], ["Bulking (Lot-C)", "Lubrication"])
        self.assertEqual(weight["used_in"][0]["product_id"], self.product.id)

        # The same unit with different limits is a different kind of value.
        self.assertEqual(rows[("PERCENT", "", "3", "4.5")]["labels"], ["LOD"])
        self.assertEqual(rows[("PERCENT", "", None, "2")]["labels"], ["Blend LOD"])

        choice = rows[("CHOICE", "", None, None)]
        self.assertEqual((choice["labels"], choice["choices"]), (["Area cleaned", "Status board correct"], OK_NOT_OK))
        self.assertEqual(choice["used_in"], [{"product_id": self.product.id, "product": self.product.name,
                                              "stage": "Lubrication"}])
        # In the order of the built-in list.
        self.assertEqual([g["kind"] for g in r.data],
                         ["NUMBER", "PERCENT", "PERCENT", "TIME_RANGE", "TEXT", "CHOICE"])

    def test_none_yet_and_only_for_those_who_manage_products(self):
        self.assertEqual(self.in_use().data, [])
        self.assertEqual(self.in_use(self.analyst).status_code, 403)
