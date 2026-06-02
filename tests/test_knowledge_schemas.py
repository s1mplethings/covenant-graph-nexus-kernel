from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))


ROOT = pathlib.Path(__file__).resolve().parents[1]


class KnowledgeSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import jsonschema  # type: ignore
            from jsonschema import Draft202012Validator, RefResolver  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"jsonschema not available: {exc}")
        cls.Draft202012Validator = Draft202012Validator
        cls.RefResolver = RefResolver
        cls.store = {}
        for path in (ROOT / "schemas").glob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            cls.store[path.resolve().as_uri()] = doc
            if "$id" in doc:
                cls.store[doc["$id"]] = doc
                cls.store[doc["$id"].rsplit("/", 1)[0] + "/" + path.name] = doc

    def validate_doc(self, doc: dict, schema_name: str) -> list:
        schema_path = ROOT / "schemas" / schema_name
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        resolver = self.RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema, store=self.store)
        validator = self.Draft202012Validator(schema, resolver=resolver)
        return list(validator.iter_errors(doc))

    def test_all_new_examples_validate_against_schemas(self) -> None:
        pack = json.loads((ROOT / "examples" / "knowledge" / "ctcp_refactor.project_knowledge_pack.json").read_text(encoding="utf-8"))
        self.assertEqual([], self.validate_doc(pack, "project_knowledge_pack.schema.json"))
        query = json.loads((ROOT / "examples" / "knowledge" / "knowledge_retrieval_query.example.json").read_text(encoding="utf-8"))
        self.assertEqual([], self.validate_doc(query, "knowledge_retrieval_query.schema.json"))
        context = json.loads((ROOT / "examples" / "knowledge" / "agent_context_pack.example.json").read_text(encoding="utf-8"))
        self.assertEqual([], self.validate_doc(context, "agent_context_pack.schema.json"))
        report = json.loads((ROOT / "examples" / "knowledge" / "knowledge_update_report.example.json").read_text(encoding="utf-8"))
        self.assertEqual([], self.validate_doc(report, "knowledge_update_report.schema.json"))
        points = json.loads((ROOT / "examples" / "knowledge" / "dialogue_keypoints.example.json").read_text(encoding="utf-8"))
        for point in points["keypoints"]:
            self.assertEqual([], self.validate_doc(point, "key_point.schema.json"))

    def test_invalid_importance_enum_fails(self) -> None:
        doc = json.loads((ROOT / "examples" / "knowledge" / "ctcp_refactor.project_knowledge_pack.json").read_text(encoding="utf-8"))
        doc["all_items"][0]["importance"] = "urgent"
        self.assertTrue(self.validate_doc(doc, "project_knowledge_pack.schema.json"))

    def test_invalid_retention_enum_fails(self) -> None:
        doc = json.loads((ROOT / "examples" / "knowledge" / "ctcp_refactor.project_knowledge_pack.json").read_text(encoding="utf-8"))
        doc["all_items"][0]["retention"] = "forever"
        self.assertTrue(self.validate_doc(doc, "project_knowledge_pack.schema.json"))

    def test_valid_agent_context_pack_passes(self) -> None:
        context = json.loads((ROOT / "examples" / "knowledge" / "agent_context_pack.example.json").read_text(encoding="utf-8"))
        self.assertEqual([], self.validate_doc(context, "agent_context_pack.schema.json"))


if __name__ == "__main__":
    unittest.main()
