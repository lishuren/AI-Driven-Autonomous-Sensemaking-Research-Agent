// Visualizer.cs
// Converts the Knowledge Graph in ResearchState into a self-contained interactive
// HTML file using an embedded D3.js force-directed layout.
//
// Output: knowledge_graph.html
//
// Node colors:
//   Red  (#e74c3c) – entity appears in at least one contradiction.
//   Blue (#2980b9) – regular entity.
//
// The generated HTML file can be opened in any modern browser.
// No external dependencies are required at runtime.

using System.Text;
using System.Text.Json;

namespace SensemakingAgent;

public static class Visualizer
{
    /// <summary>
    /// Generates <c>knowledge_graph.html</c> (or the path given in
    /// <paramref name="outputPath"/>) from the Knowledge Graph embedded in
    /// <paramref name="state"/>.
    /// </summary>
    public static void GenerateHtml(
        ResearchState state,
        string outputPath = "knowledge_graph.html")
    {
        var graph = state.KnowledgeGraph;
        if (graph.Triplets.Count == 0)
        {
            Console.WriteLine("[Visualizer] No triplets to visualise.");
            return;
        }

        // Collect the set of entities that appear in contradictions.
        var contradictedEntities = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var c in state.Contradictions)
        {
            // Try to match claim text to entity names.
            foreach (var entity in graph.Entities)
            {
                if (c.ClaimA.Contains(entity, StringComparison.OrdinalIgnoreCase) ||
                    c.ClaimB.Contains(entity, StringComparison.OrdinalIgnoreCase))
                {
                    contradictedEntities.Add(entity);
                }
            }
        }

        // Build node and link lists for D3.
        var nodeSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var t in graph.Triplets)
        {
            nodeSet.Add(t.Subject);
            nodeSet.Add(t.Object);
        }
        // Also include entities declared by the Analyst that may not appear in triplets yet.
        foreach (var e in graph.Entities)
            nodeSet.Add(e);

        var nodeList = nodeSet.Select(n => new
        {
            id = n,
            color = contradictedEntities.Contains(n) ? "#e74c3c" : "#2980b9",
            disputed = contradictedEntities.Contains(n)
        }).ToList();

        var linkList = graph.Triplets.Select(t => new
        {
            source = t.Subject,
            target = t.Object,
            label = t.Predicate,
            evidence = t.Evidence.Length > 120 ? t.Evidence[..120] + "…" : t.Evidence
        }).ToList();

        string nodesJson = JsonSerializer.Serialize(nodeList);
        string linksJson = JsonSerializer.Serialize(linkList);

        string html = BuildHtml(nodesJson, linksJson, state.CurrentQuery,
            graph.Entities.Count, graph.Triplets.Count, state.Contradictions.Count);

        File.WriteAllText(outputPath, html, Encoding.UTF8);
        Console.WriteLine($"[Visualizer] Knowledge graph saved to: {Path.GetFullPath(outputPath)}");
    }

    // ---------------------------------------------------------------------------
    // HTML template
    // ---------------------------------------------------------------------------

    private static string BuildHtml(
        string nodesJson, string linksJson,
        string topic, int entityCount, int tripletCount, int contradictionCount)
    {
        return $$"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
              <meta charset="UTF-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1.0" />
              <title>Sensemaking Knowledge Graph</title>
              <script src="https://d3js.org/d3.v7.min.js"></script>
              <style>
                body { margin: 0; font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; }
                #header { padding: 12px 20px; background: #16213e; border-bottom: 1px solid #0f3460; }
                #header h1 { margin: 0; font-size: 1.2rem; }
                #stats { font-size: 0.85rem; color: #aaa; margin-top: 4px; }
                #legend { display: flex; gap: 18px; margin-top: 8px; font-size: 0.8rem; }
                .legend-item { display: flex; align-items: center; gap: 6px; }
                .legend-dot { width: 12px; height: 12px; border-radius: 50%; }
                svg { width: 100vw; height: calc(100vh - 80px); }
                .link { stroke: #555; stroke-opacity: 0.6; }
                .link-label { font-size: 9px; fill: #aaa; pointer-events: none; }
                .node circle { stroke: #fff; stroke-width: 1.5px; cursor: pointer; }
                .node text { font-size: 11px; fill: #eee; pointer-events: none; }
                #tooltip {
                  position: absolute; background: rgba(0,0,0,0.85);
                  padding: 8px 12px; border-radius: 6px; font-size: 0.8rem;
                  pointer-events: none; display: none; max-width: 280px;
                  border: 1px solid #555; line-height: 1.5;
                }
              </style>
            </head>
            <body>
              <div id="header">
                <h1>🧠 Sensemaking Knowledge Graph — <em>{{topic}}</em></h1>
                <div id="stats">
                  Entities: <strong>{{entityCount}}</strong> &nbsp;|&nbsp;
                  Triplets: <strong>{{tripletCount}}</strong> &nbsp;|&nbsp;
                  Contradictions: <strong>{{contradictionCount}}</strong>
                </div>
                <div id="legend">
                  <div class="legend-item">
                    <div class="legend-dot" style="background:#2980b9"></div> Regular entity
                  </div>
                  <div class="legend-item">
                    <div class="legend-dot" style="background:#e74c3c"></div> Disputed entity
                  </div>
                </div>
              </div>
              <div id="tooltip"></div>
              <svg></svg>

              <script>
                const nodes = {{nodesJson}};
                const links = {{linksJson}};

                const svg = d3.select("svg");
                const width = window.innerWidth;
                const height = window.innerHeight - 80;

                svg.attr("viewBox", [0, 0, width, height]);

                const simulation = d3.forceSimulation(nodes)
                  .force("link", d3.forceLink(links).id(d => d.id).distance(120))
                  .force("charge", d3.forceManyBody().strength(-300))
                  .force("center", d3.forceCenter(width / 2, height / 2))
                  .force("collision", d3.forceCollide(30));

                // Arrow markers
                svg.append("defs").selectAll("marker")
                  .data(["arrow"])
                  .join("marker")
                    .attr("id", d => d)
                    .attr("viewBox", "0 -5 10 10")
                    .attr("refX", 22).attr("refY", 0)
                    .attr("markerWidth", 6).attr("markerHeight", 6)
                    .attr("orient", "auto")
                  .append("path")
                    .attr("fill", "#555")
                    .attr("d", "M0,-5L10,0L0,5");

                const link = svg.append("g")
                  .selectAll("line")
                  .data(links)
                  .join("line")
                    .attr("class", "link")
                    .attr("stroke-width", 1.5)
                    .attr("marker-end", "url(#arrow)");

                const linkLabel = svg.append("g")
                  .selectAll("text")
                  .data(links)
                  .join("text")
                    .attr("class", "link-label")
                    .text(d => d.label);

                const node = svg.append("g")
                  .selectAll("g")
                  .data(nodes)
                  .join("g")
                    .attr("class", "node")
                    .call(d3.drag()
                      .on("start", dragstarted)
                      .on("drag", dragged)
                      .on("end", dragended));

                node.append("circle")
                  .attr("r", 14)
                  .attr("fill", d => d.color);

                node.append("text")
                  .attr("dx", 17).attr("dy", 4)
                  .text(d => d.id);

                const tooltip = document.getElementById("tooltip");

                node.on("mouseover", (event, d) => {
                  const related = links.filter(
                    l => (l.source.id || l.source) === d.id ||
                         (l.target.id || l.target) === d.id);
                  const lines = related.map(
                    l => `${l.source.id || l.source} <em>${l.label}</em> ${l.target.id || l.target}`);
                  tooltip.innerHTML =
                    `<strong>${d.id}</strong>${d.disputed ? " ⚠ Disputed" : ""}<br/>` +
                    (lines.length ? lines.join("<br/>") : "No direct connections");
                  tooltip.style.display = "block";
                }).on("mousemove", event => {
                  tooltip.style.left = (event.pageX + 12) + "px";
                  tooltip.style.top  = (event.pageY - 10) + "px";
                }).on("mouseleave", () => {
                  tooltip.style.display = "none";
                });

                simulation.on("tick", () => {
                  link
                    .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
                    .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
                  linkLabel
                    .attr("x", d => (d.source.x + d.target.x) / 2)
                    .attr("y", d => (d.source.y + d.target.y) / 2);
                  node.attr("transform", d => `translate(${d.x},${d.y})`);
                });

                function dragstarted(event, d) {
                  if (!event.active) simulation.alphaTarget(0.3).restart();
                  d.fx = d.x; d.fy = d.y;
                }
                function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
                function dragended(event, d) {
                  if (!event.active) simulation.alphaTarget(0);
                  d.fx = null; d.fy = null;
                }
              </script>
            </body>
            </html>
            """;
    }
}
