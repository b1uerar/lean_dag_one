from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lean_dag as dag


FIXTURES = Path(__file__).parent / "fixtures"


class GraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = dag.finalize_graph(dag.extract(
            dag.ROOT / "examples/Incomplete.lean", "Demo.target", None), sorry_only=False)
        cls.nodes = {n["id"]: n for n in cls.graph["nodes"]}

    def test_dependency_and_sorry_propagation(self):
        self.assertEqual(set(self.nodes), {
            "Demo.target", "Demo.intermediate", "Demo.unfinished", "Demo.finished"})
        self.assertEqual(self.graph["scope"], "input_file")
        self.assertEqual(self.graph["sorry_scope"], "input_file")
        self.assertEqual(self.nodes["Demo.finished"]["proof_dependencies"], [])
        self.assertEqual(self.nodes["Demo.intermediate"]["proof_dependencies"], ["Demo.unfinished"])
        self.assertTrue(self.nodes["Demo.unfinished"]["direct_sorry"])
        self.assertTrue(self.nodes["Demo.unfinished"]["has_sorry"])
        self.assertFalse(self.nodes["Demo.target"]["has_sorry"])
        self.assertTrue(self.nodes["Demo.target"]["depends_on_sorry"])
        self.assertTrue(self.nodes["Demo.finished"]["sorry_free"])
        positions = {n: i for i, n in enumerate(self.graph["topological_order"])}
        for edge in self.graph["edges"]:
            self.assertLess(positions[edge["source"]], positions[edge["target"]])

    def test_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = dag.write_outputs(self.graph, output)
            self.assertEqual(len(paths), 4)
            self.assertEqual(json.loads((output / "graph.json").read_text()), self.graph)
            svg = ET.parse(output / "graph.svg")
            groups = svg.findall(".//{http://www.w3.org/2000/svg}g")
            self.assertEqual(len(groups), len(self.nodes))
            self.assertIn('"Demo.unfinished" -> "Demo.intermediate"', (output / "graph.dot").read_text())
            page = (output / "graph.html").read_text()
            self.assertNotIn("/*GRAPH_DATA*/", page)
            self.assertNotIn("<!--GRAPH-->", page)
            self.assertNotIn('src="http', page)

    def test_reject_cycle(self):
        raw = json.loads(json.dumps(self.graph))
        for node in raw["nodes"]:
            if node["id"] == "Demo.unfinished":
                node["proof_dependencies"].append("Demo.target")
        with self.assertRaisesRegex(ValueError, "cycle"):
            dag.finalize_graph(raw)

    def test_html_escapes_data(self):
        graph = json.loads(json.dumps(self.graph))
        graph["nodes"][0]["statement"] = "</script><script>alert(1)</script>"
        page = dag.render_html(graph, dag.render_svg(graph))
        self.assertNotIn("</script><script>alert(1)", page)

    def test_sorry_only_default(self):
        graph = dag.finalize_graph(self.graph)
        self.assertTrue(graph["sorry_only"])
        self.assertEqual({n["id"] for n in graph["nodes"]},
                         {"Demo.target", "Demo.intermediate", "Demo.unfinished"})
        self.assertEqual(graph["summary"]["edges"], 2)
        root = next(n for n in graph["nodes"] if n["id"] == graph["root"])
        self.assertEqual(root["proof_dependencies"], ["Demo.intermediate"])
        self.assertIn("Demo.finished", next(n for n in self.graph["nodes"]
                                           if n["id"] == graph["root"])["proof_dependencies"])

    def test_sorry_paths_branch_merge_and_root_sorry(self):
        def node(name, deps=(), sorry=False):
            return {"id": name, "kind": "theorem", "has_sorry": sorry,
                    "statement_dependencies": [], "proof_dependencies": list(deps)}
        raw = {"root": "root", "nodes": [
            node("root", ["left", "right", "clean"], True),
            node("left", ["hole", "clean"]), node("right", ["hole", "second"]),
            node("hole", ["deeper", "clean"], True), node("deeper", sorry=True),
            node("second", sorry=True), node("clean"), node("unreachable", sorry=True)]}
        graph = dag.finalize_graph(raw)
        self.assertEqual({n["id"] for n in graph["nodes"]},
                         {"root", "left", "right", "hole", "deeper", "second"})
        self.assertEqual({(e["source"], e["target"]) for e in graph["edges"]},
                         {("left", "root"), ("right", "root"), ("hole", "left"),
                          ("hole", "right"), ("second", "right"), ("deeper", "hole")})

    def test_no_sorry_keeps_root(self):
        raw = json.loads(json.dumps(self.graph))
        for node in raw["nodes"]:
            node["has_sorry"] = False
        graph = dag.finalize_graph(raw)
        self.assertEqual([n["id"] for n in graph["nodes"]], [raw["root"]])
        self.assertEqual(graph["edges"], [])
        self.assertEqual(graph["topological_order"], [raw["root"]])

    def test_cli_sorry_option(self):
        with tempfile.TemporaryDirectory() as directory:
            for flags, count in (([], 3), (["--sorry-only"], 3), (["--no-sorry-only"], 4)):
                result = subprocess.run([sys.executable, str(dag.ROOT / "lean_dag.py"),
                    str(dag.ROOT / "examples/Incomplete.lean"), "Demo.target", "-o", directory,
                    *flags], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                graph = json.loads((Path(directory) / "graph.json").read_text())
                self.assertEqual(graph["summary"]["nodes"], count)
                self.assertEqual(len(ET.parse(Path(directory) / "graph.svg").findall(
                    ".//{http://www.w3.org/2000/svg}g")), count)


class LeanTests(unittest.TestCase):
    def extract_case(self, theorem):
        graph = dag.finalize_graph(dag.extract(FIXTURES / "EdgeCases.lean", theorem, None),
                                   sorry_only=False)
        return graph, {n["id"]: n for n in graph["nodes"]}

    def test_definition_dependencies(self):
        graph, nodes = self.extract_case("Cases.through_definition")
        self.assertEqual(nodes[graph["root"]]["proof_dependencies"], ["Cases.missing"])
        self.assertNotIn("Cases.proofHelper", nodes)
        self.assertNotIn("Cases.unused", nodes)

    def test_sorry_in_definition(self):
        graph, nodes = self.extract_case("through_sorry_definition")
        root = nodes[graph["root"]]
        self.assertFalse(root["direct_sorry"])
        self.assertTrue(root["has_sorry"])

    def test_private_theorem(self):
        graph, nodes = self.extract_case("Cases.through_private")
        private_id = nodes[graph["root"]]["proof_dependencies"][0]
        self.assertEqual(nodes[private_id]["name"], "Cases.privateLemma")
        self.assertTrue(nodes[private_id]["depends_on_sorry"])

    def test_axiom(self):
        _, nodes = self.extract_case("Cases.through_axiom")
        self.assertEqual(set(nodes), {"Cases.through_axiom"})
        self.assertTrue(nodes["Cases.through_axiom"]["sorry_free"])

    def test_sorry_target_has_no_metadata_dependencies(self):
        graph, nodes = self.extract_case("Cases.unfinished_target")
        self.assertEqual(len(nodes), 1)
        self.assertTrue(nodes[graph["root"]]["proof_sorry"])

    def test_sorry_statement(self):
        graph, nodes = self.extract_case("Cases.sorry_statement")
        self.assertTrue(nodes[graph["root"]]["statement_sorry"])
        self.assertTrue(nodes[graph["root"]]["proof_sorry"])

    def test_bad_names_and_node_limit(self):
        for theorem, message in (("does_not_exist", "not found"), ("duplicate", "Ambiguous")):
            with self.subTest(theorem=theorem), self.assertRaisesRegex(RuntimeError, message):
                self.extract_case(theorem)
        with self.assertRaisesRegex(RuntimeError, "exceeds 1 nodes"):
            dag.extract(FIXTURES / "EdgeCases.lean", "through_definition", None, max_nodes=1)

    def test_statement_dependency(self):
        graph, nodes = self.extract_case("Cases.statement_dependency")
        self.assertEqual(nodes[graph["root"]]["statement_dependencies"], ["Cases.missing"])
        edge = next(e for e in graph["edges"] if e["source"] == "Cases.missing")
        self.assertEqual(edge["kinds"], ["statement"])
        self.assertIn('style="dashed"', dag.render_dot(graph))

    def test_elaboration_errors_do_not_produce_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Bad.lean"
            source.write_text("theorem broken : True := by exact unknown_theorem\n")
            result = subprocess.run([sys.executable, str(dag.ROOT / "lean_dag.py"),
                                     str(source), "broken", "-o", str(Path(directory) / "out")],
                                    text=True, capture_output=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failed Lean checking", result.stderr)
            self.assertFalse((Path(directory) / "out").exists())

    def test_lake_excludes_imports_and_their_sorries(self):
        with tempfile.TemporaryDirectory(prefix="lean dag test ") as directory:
            project = Path(directory) / "project"
            shutil.copytree(FIXTURES / "project", project,
                            ignore=shutil.ignore_patterns('.lake', 'lake-manifest.json'))
            source = project / "Fixture/Target.lean"
            self.assertEqual(dag.find_project(source), project)
            graph = dag.finalize_graph(dag.extract(source, "imported_target", project))
            nodes = {n["id"]: n for n in graph["nodes"]}
            self.assertEqual(set(nodes), {"imported_target"})
            self.assertTrue(nodes[graph["root"]]["sorry_free"])
            self.assertEqual(graph["edges"], [])
            local = dag.finalize_graph(dag.extract(source, "Imported.local_target", project))
            nodes = {n["id"]: n for n in local["nodes"]}
            self.assertEqual(set(nodes), {"Imported.local_target", "Imported.local_missing"})
            self.assertTrue(nodes["Imported.local_missing"]["has_sorry"])
            self.assertTrue(nodes["Imported.local_target"]["depends_on_sorry"])
            self.assertTrue(all(n["module"] == "Fixture.Target" for n in nodes.values()))


if __name__ == "__main__":
    unittest.main()
