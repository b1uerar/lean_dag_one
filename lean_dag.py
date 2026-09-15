#!/usr/bin/env python3
"""Extract and render theorem dependencies within one Lean 4.26.0 source file."""

from __future__ import annotations

import argparse
from collections import defaultdict
from graphlib import CycleError, TopologicalSorter
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import webbrowser
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
TOOLCHAIN = "leanprover/lean4:v4.26.0"
PALETTE = {
    "sorry": ("#fff1f2", "#be123c", "Contains sorry"),
    "depends_on_sorry": ("#fefce8", "#a16207", "Depends on sorry"),
    "complete": ("#f0fdfa", "#0f766e", "Sorry-free"),
    "axiom": ("#f4f4f5", "#52525b", "Axiom"),
}


def run(command: list[str], cwd: Path, timeout: int) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip() or
                           f"Command failed with exit code {result.returncode}: {command[0]}")
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.stdout


def find_project(source: Path) -> Path | None:
    for directory in source.parents:
        if any((directory / name).is_file() for name in ("lakefile.toml", "lakefile.lean")):
            return directory
    return None


def extract(source: Path, theorem: str, project: Path | None,
            timeout: int = 300, max_nodes: int = 10000) -> dict:
    if not shutil.which("lean"):
        raise RuntimeError("Lean/elan is not on PATH. Install Lean 4.26.0 with elan first.")
    cwd = project or source.parent
    prefix = ["lake", f"+{TOOLCHAIN}", "env"] if project else []
    lean = ["lean"] if project else ["lean", f"+{TOOLCHAIN}"]
    if project:
        toolchain_file = project / "lean-toolchain"
        if toolchain_file.exists():
            configured = toolchain_file.read_text().strip()
            if configured not in (TOOLCHAIN, "v4.26.0"):
                raise RuntimeError(f"Project requires {configured}; this extractor supports {TOOLCHAIN}.")
    version = run(prefix + lean + ["--version"], cwd, timeout)
    if not version.startswith("Lean (version 4.26.0,"):
        raise RuntimeError(f"Expected Lean 4.26.0, got: {version.strip()}")
    with tempfile.TemporaryDirectory(prefix="lean-dag-") as tmp:
        temp = Path(tmp)
        setup_arg = "-"
        if project:
            print("Preparing imported modules with Lake...", file=sys.stderr)
            setup_text = run(["lake", f"+{TOOLCHAIN}", "setup-file", str(source)], cwd, timeout)
            setup = json.loads(setup_text)
            setup_path = temp / "setup.json"
            setup_path.write_text(json.dumps(setup), encoding="utf-8")
            setup_arg = str(setup_path)
        raw_path = temp / "raw.json"
        print(f"Checking {source.name} and extracting {theorem}...", file=sys.stderr)
        diagnostics = run(prefix + lean + ["--run", str(ROOT / "ExtractDag.lean"),
                          str(source), theorem, str(raw_path), setup_arg, str(max_nodes)], cwd, timeout)
        if diagnostics.strip():
            print(diagnostics.strip(), file=sys.stderr)
        return json.loads(raw_path.read_text(encoding="utf-8"))


def finalize_graph(raw: dict, sorry_only: bool = True) -> dict:
    nodes = {node["id"]: dict(node) for node in raw["nodes"]}
    if len(nodes) != len(raw["nodes"]) or raw["root"] not in nodes:
        raise ValueError("Invalid extractor output: duplicate nodes or missing root")
    dependencies = {}
    edges = []
    for name, node in sorted(nodes.items()):
        statement = set(node["statement_dependencies"])
        proof = set(node["proof_dependencies"])
        dependencies[name] = sorted(statement | proof)
        for dependency in dependencies[name]:
            if dependency not in nodes:
                raise ValueError(f"Missing dependency node: {dependency}")
            kinds = [kind for kind, used in (("statement", statement), ("proof", proof))
                     if dependency in used]
            edges.append({"source": dependency, "target": name, "kinds": kinds})
    try:
        order = list(TopologicalSorter(dependencies).static_order())
    except CycleError as error:
        raise ValueError(f"Dependency cycle detected; cannot export a DAG: {error.args[1]}") from error
    for name in order:
        node = nodes[name]
        node["depends_on_sorry"] = any(nodes[d]["has_sorry"] or nodes[d]["depends_on_sorry"]
                                       for d in dependencies[name])
        node["sorry_free"] = not (node["has_sorry"] or node["depends_on_sorry"])
        node["status"] = ("sorry" if node["has_sorry"] else
                          "depends_on_sorry" if node["depends_on_sorry"] else
                          "axiom" if node["kind"] == "axiom" else "complete")
    if sorry_only:
        # Follow dependencies backwards from the root. Keep every branch that
        # reaches a sorry, including all alternate paths to shared dependencies.
        reachable = set()
        pending = [raw["root"]]
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            pending.extend(dependencies[name])
        retained = {name for name in reachable if not nodes[name]["sorry_free"]}
        retained.add(raw["root"])
        nodes = {name: node for name, node in nodes.items() if name in retained}
        for node in nodes.values():
            for field in ("statement_dependencies", "proof_dependencies"):
                node[field] = [name for name in node[field] if name in retained]
        edges = [edge for edge in edges if edge["source"] in retained and edge["target"] in retained]
        order = [name for name in order if name in retained]
    return {**raw, "nodes": [nodes[name] for name in sorted(nodes)], "edges": edges,
            "sorry_only": sorry_only,
            "edge_direction": "dependency_to_dependent", "topological_order": order,
            "is_dag": True,
            "summary": {"nodes": len(nodes), "edges": len(edges),
                        "contains_sorry": sum(n["has_sorry"] for n in nodes.values()),
                        "depends_on_sorry": sum(n["depends_on_sorry"] for n in nodes.values()),
                        "axioms": sum(n["kind"] == "axiom" for n in nodes.values())}}


def render_dot(graph: dict) -> str:
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ["digraph theorem_dependencies {", "  rankdir=LR;",
             '  graph [bgcolor="white", pad=0.4];',
             '  node [shape=box, style="rounded,filled", fontname="sans-serif"];',
             '  edge [color="#9ca3af"];']
    for node in graph["nodes"]:
        fill, color, status = PALETTE[node["status"]]
        label = node["name"] + "\n" + status
        width = "3" if node["id"] == graph["root"] else "1"
        lines.append(f'  {quote(node["id"])} [label={quote(label)}, fillcolor="{fill}", '
                     f'color="{color}", penwidth={width}, tooltip={quote(node["statement"])}];')
    for edge in graph["edges"]:
        style = "dashed" if edge["kinds"] == ["statement"] else "solid"
        lines.append(f'  {quote(edge["source"])} -> {quote(edge["target"])} '
                     f'[style="{style}", tooltip={quote(", ".join(edge["kinds"]))}];')
    return "\n".join(lines + ["}", ""])


def layout(graph: dict) -> tuple[dict, dict, int, int]:
    predecessors = defaultdict(list)
    successors = defaultdict(list)
    for edge in graph["edges"]:
        predecessors[edge["target"]].append(edge["source"])
        successors[edge["source"]].append(edge["target"])
    ranks = {}
    layers = defaultdict(list)
    for name in graph["topological_order"]:
        ranks[name] = max((ranks[d] + 1 for d in predecessors[name]), default=0)
        layers[ranks[name]].append(name)
    # Reserve an empty slot in every intervening column so long edges cannot
    # cross a theorem box and appear to connect to the wrong declaration.
    predecessors.clear()
    successors.clear()
    routes = {}
    for edge in graph["edges"]:
        source, target = edge["source"], edge["target"]
        route = [source]
        for rank in range(ranks[source] + 1, ranks[target]):
            dummy = (source, target, rank)
            layers[rank].append(dummy)
            route.append(dummy)
        route.append(target)
        routes[source, target] = route
        for start, end in zip(route, route[1:]):
            predecessors[end].append(start)
            successors[start].append(end)
    # Barycenter sweeps reduce crossings while keeping each node in a fixed column.
    order = {name: i for layer in layers.values() for i, name in enumerate(sorted(layer, key=str))}
    for sweep in range(6):
        forward = sweep % 2 == 0
        for rank in sorted(layers, reverse=not forward):
            neighbors = predecessors if forward else successors
            def center(name):
                adjacent = neighbors[name]
                return sum(order[n] for n in adjacent) / len(adjacent) if adjacent else order[name]
            layers[rank].sort(key=lambda name: (center(name), str(name)))
            order.update({name: i for i, name in enumerate(layers[rank])})
    height = max(len(layer) for layer in layers.values()) * 112 + 64
    width = len(layers) * 368 + 32
    positions = {}
    for rank, layer in layers.items():
        offset = (height - len(layer) * 112) / 2
        for index, name in enumerate(layer):
            positions[name] = (32 + rank * 368, offset + index * 112)
    return positions, routes, width, height


def render_svg(graph: dict) -> str:
    positions, routes, width, height = layout(graph)
    svg = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "viewBox": f"0 0 {width} {height}",
                             "width": str(width), "height": str(height), "role": "img",
                             "aria-label": f"Theorem dependency graph for {graph['root']}"})
    ET.SubElement(svg, "title").text = f"Dependencies of {graph['root']}"
    defs = ET.SubElement(svg, "defs")
    marker = ET.SubElement(defs, "marker", {"id": "arrow", "viewBox": "0 0 10 10", "refX": "9",
                                          "refY": "5", "markerWidth": "7", "markerHeight": "7",
                                          "orient": "auto-start-reverse"})
    ET.SubElement(marker, "path", {"d": "M 0 0 L 10 5 L 0 10 z", "fill": "#9ca3af"})
    ET.SubElement(svg, "rect", {"width": "100%", "height": "100%", "fill": "#ffffff"})
    for edge in graph["edges"]:
        route = routes[edge["source"], edge["target"]]
        commands = []
        for index, (start, end) in enumerate(zip(route, route[1:])):
            x1, y1 = positions[start]
            x2, y2 = positions[end]
            x1, y1, y2 = x1 + 280, y1 + 43, y2 + 43
            middle = (x1 + x2) / 2
            if index == 0:
                commands.append(f"M {x1} {y1}")
            final = end == edge["target"]
            commands.append(f"C {middle} {y1}, {middle} {y2}, {x2 - 2 if final else x2} {y2}")
            if not final:
                commands.append(f"L {x2 + 280} {y2}")
        attrs = {"d": " ".join(commands),
                 "fill": "none", "stroke": "#9ca3af", "stroke-width": "1.4", "marker-end": "url(#arrow)",
                 "class": "edge", "data-source": edge["source"], "data-target": edge["target"]}
        if edge["kinds"] == ["statement"]:
            attrs["stroke-dasharray"] = "5 4"
        path = ET.SubElement(svg, "path", attrs)
        ET.SubElement(path, "title").text = f"{edge['source']} -> {edge['target']} ({', '.join(edge['kinds'])})"
    for node in graph["nodes"]:
        x, y = positions[node["id"]]
        fill, color, status = PALETTE[node["status"]]
        group = ET.SubElement(svg, "g", {"class": "node", "data-id": node["id"], "tabindex": "0",
                                        "role": "button", "aria-label": f"{node['name']}: {status}",
                                        "transform": f"translate({x},{y})"})
        ET.SubElement(group, "title").text = f"{node['name']}\n{status}\n{node['statement']}"
        ET.SubElement(group, "rect", {"width": "280", "height": "86", "rx": "6", "fill": fill,
                                     "stroke": color, "stroke-width": "3" if node["id"] == graph["root"] else "1"})
        label = textwrap.wrap(node["name"], width=34, break_long_words=True, break_on_hyphens=False)
        for i, line in enumerate(label[:2]):
            if i == 1 and len(label) > 2:
                line = line[:31] + "..."
            ET.SubElement(group, "text", {"x": "14", "y": str(25 + 18 * i), "fill": "#18181b",
                                         "font-size": "13", "font-family": "monospace"}).text = line
        ET.SubElement(group, "text", {"x": "14", "y": "69", "fill": color,
                                     "font-size": "12", "font-family": "sans-serif"}).text = status
    return ET.tostring(svg, encoding="unicode")


def render_html(graph: dict, svg: str) -> str:
    template = (ROOT / "viewer.html").read_text(encoding="utf-8")
    data = json.dumps(graph, ensure_ascii=True).replace("<", "\\u003c")
    return (template.replace("<!--GRAPH-->", svg)
            .replace("/*GRAPH_DATA*/null", data)
            .replace("<!--ROOT_NAME-->", html.escape(graph["root"])))


def write_outputs(graph: dict, output: Path) -> list[Path]:
    svg = render_svg(graph)
    artifacts = {"graph.json": json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
                 "graph.dot": render_dot(graph), "graph.svg": svg, "graph.html": render_html(graph, svg)}
    output.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (output / name).write_text(content, encoding="utf-8")
    return [output / name for name in artifacts]


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Lean source file; explicit sorry is allowed")
    parser.add_argument("theorem", help="Theorem name, preferably fully qualified")
    parser.add_argument("--output-dir", "-o", type=Path, default=Path("output"))
    parser.add_argument("--project", type=Path, help="Lake project root; detected automatically by default")
    parser.add_argument("--max-nodes", type=positive_int, default=10000)
    parser.add_argument("--timeout", type=positive_int, default=300, help="Timeout per Lean/Lake command in seconds")
    parser.add_argument("--open", action="store_true", help="Open the generated HTML in your browser")
    parser.add_argument("--sorry-only", action=argparse.BooleanOptionalAction, default=True,
                        help="Keep only the root and all paths to sorry nodes (default: enabled); "
                             "--no-sorry-only exports the full file-local graph")
    args = parser.parse_args(argv)
    try:
        source = args.file.resolve()
        if not source.is_file() or source.suffix != ".lean":
            raise ValueError(f"Not a Lean source file: {source}")
        project = args.project.resolve() if args.project else find_project(source)
        if project and not any((project / n).is_file() for n in ("lakefile.toml", "lakefile.lean")):
            raise ValueError(f"No lakefile found in {project}")
        graph = finalize_graph(extract(source, args.theorem, project, args.timeout, args.max_nodes),
                               sorry_only=args.sorry_only)
        paths = write_outputs(graph, args.output_dir.resolve())
        summary = graph["summary"]
        print(f"{graph['root']}: {summary['nodes']} nodes, {summary['edges']} edges; "
              f"{summary['contains_sorry']} contain sorry, {summary['depends_on_sorry']} depend on sorry.")
        for path in paths:
            print(path)
        if args.open:
            webbrowser.open(paths[-1].as_uri())
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"lean-dag: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
