// Graph.cs
// SensemakingGraph: The cyclic state-machine that orchestrates Scout → Analyst → Critic
// and routes back to Scout or forward to Writer based on the current ResearchState.
//
// Routing logic (ShouldContinue):
//   1. High-severity contradiction found AND iteration < 3 AND no tie-breaker yet
//      → generate tie-breaker query, route back to Scout.
//   2. ResearchGaps not empty AND iteration < MAX_ITERATIONS
//      → set current query to address the gap, route back to Scout.
//   3. Graph saturation (< 10 % new triplets) OR iteration >= MAX_ITERATIONS
//      → route to Writer.
//
// This mirrors the LangGraph conditional-edge pattern described in the PRD.

using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace SensemakingAgent;

// ---------------------------------------------------------------------------
// Route enum
// ---------------------------------------------------------------------------

internal enum AgentRoute
{
    Scout,
    Writer
}

// ---------------------------------------------------------------------------
// SensemakingGraph
// ---------------------------------------------------------------------------

/// <summary>
/// Assembles and runs the full Sensemaking research loop.
/// </summary>
public sealed class SensemakingGraph : IDisposable
{
    // Maximum iterations before the agent stops regardless of remaining gaps.
    private const int MaxIterations = 5;
    // Maximum tie-breaker searches per session.
    private const int MaxTieBreakers = 3;

    private readonly ResearchScraper _scout;
    private readonly AnalystNode _analyst;
    private readonly CriticNode _critic;
    private readonly WriterNode _writer;
    private readonly LlmGateway _llm;

    public SensemakingGraph(
        ResearchScraper? scout = null,
        AnalystNode? analyst = null,
        CriticNode? critic = null,
        WriterNode? writer = null,
        LlmGateway? llm = null)
    {
        _llm = llm ?? new LlmGateway();
        _scout = scout ?? new ResearchScraper(ScraperConfig.FromEnvironment());
        _analyst = analyst ?? new AnalystNode(_llm);
        _critic = critic ?? new CriticNode(_llm);
        _writer = writer ?? new WriterNode(_llm);
    }

    // ---- Public entry point ----

    /// <summary>
    /// Runs the full Sensemaking loop for <paramref name="query"/> and returns
    /// both the final <see cref="ResearchBrief"/> and the accumulated
    /// <see cref="ResearchState"/> for downstream use (e.g. visualisation).
    /// </summary>
    public async Task<(ResearchBrief Brief, ResearchState FinalState)> RunAsync(
        string query, CancellationToken ct = default)
    {
        Console.WriteLine($"[Graph] Starting Sensemaking loop for: \"{query}\"");
        Console.WriteLine($"[Graph] Max iterations: {MaxIterations}");
        Console.WriteLine();

        var state = ResearchState.Create(query);
        int tieBreakerCount = 0;

        while (true)
        {
            ct.ThrowIfCancellationRequested();

            // ── Scout ──────────────────────────────────────────────────────
            Console.WriteLine(
                $"[Graph] ── Iteration {state.IterationCount + 1} ── " +
                $"Scout: \"{state.CurrentQuery}\"");

            var docs = await _scout.RunSearchAsync(state.CurrentQuery, ct);
            Console.WriteLine($"[Graph] Scout returned {docs.Count} document(s).");

            state = state.ApplyUpdate(new ResearchStateUpdate { NewDocuments = docs });

            // ── Analyst ───────────────────────────────────────────────────
            var analystDelta = await _analyst.RunAsync(state, ct);
            state = state.ApplyUpdate(analystDelta);

            // ── Critic ────────────────────────────────────────────────────
            var criticDelta = await _critic.RunAsync(state, ct);
            state = state.ApplyUpdate(criticDelta);

            // Increment iteration counter after the full Scout→Analyst→Critic pass.
            state = state.ApplyUpdate(new ResearchStateUpdate { IncrementIteration = true });

            Console.WriteLine(
                $"[Graph] After iteration {state.IterationCount}: " +
                $"{state.KnowledgeGraph.Triplets.Count} triplets, " +
                $"{state.Contradictions.Count} contradiction(s), " +
                $"{state.ResearchGaps.Count} gap(s).");

            // ── Router ────────────────────────────────────────────────────
            var route = ShouldContinue(state, tieBreakerCount);

            if (route == AgentRoute.Writer)
            {
                Console.WriteLine("[Graph] → Routing to Writer.");
                break;
            }

            // Scout again – update the query before looping.
            string nextQuery;

            bool hasHighConflict = state.Contradictions
                .Any(c => c.Severity == ContradictionSeverity.High);

            if (hasHighConflict && !state.TieBreakerDispatched
                && tieBreakerCount < MaxTieBreakers)
            {
                nextQuery = await GenerateTieBreakerQueryAsync(state, ct);
                tieBreakerCount++;
                state = state.ApplyUpdate(new ResearchStateUpdate
                {
                    CurrentQuery = nextQuery,
                    TieBreakerDispatched = true
                });
                Console.WriteLine($"[Graph] → Tie-Breaker search: \"{nextQuery}\"");
            }
            else if (state.ResearchGaps.Count > 0)
            {
                nextQuery = state.ResearchGaps[0];
                state = state.ApplyUpdate(new ResearchStateUpdate
                {
                    CurrentQuery = nextQuery,
                    ResolvedGaps = [nextQuery],
                    TieBreakerDispatched = false   // reset for next conflict
                });
                Console.WriteLine($"[Graph] → Gap search: \"{nextQuery}\"");
            }
            else
            {
                // Should not reach here; guard against infinite loop.
                break;
            }
        }

        // ── Writer ─────────────────────────────────────────────────────────
        Console.WriteLine("[Graph] Running Writer node…");
        var brief = await _writer.RunAsync(state, ct);

        return (brief, state);
    }

    // ---- Router logic ----

    /// <summary>
    /// Evaluates the current state and decides whether to loop back to Scout or
    /// proceed to the Writer.
    /// </summary>
    private static AgentRoute ShouldContinue(ResearchState state, int tieBreakerCount)
    {
        if (state.IterationCount >= MaxIterations)
        {
            Console.WriteLine("[Router] Max iterations reached → Writer.");
            return AgentRoute.Writer;
        }

        bool hasHighConflict = state.Contradictions
            .Any(c => c.Severity == ContradictionSeverity.High);

        if (hasHighConflict && !state.TieBreakerDispatched
            && tieBreakerCount < MaxTieBreakers)
        {
            Console.WriteLine("[Router] High-severity contradiction → Tie-Breaker Scout.");
            return AgentRoute.Scout;
        }

        if (state.ResearchGaps.Count > 0)
        {
            Console.WriteLine($"[Router] {state.ResearchGaps.Count} gap(s) remaining → Scout.");
            return AgentRoute.Scout;
        }

        if (!state.GraphGrewSignificantly())
        {
            Console.WriteLine("[Router] Graph saturated (< 10 % growth) → Writer.");
            return AgentRoute.Writer;
        }

        Console.WriteLine("[Router] Graph still growing → Scout for another pass.");
        return AgentRoute.Scout;
    }

    // ---- Tie-Breaker query generation ----

    /// <summary>
    /// Prompts the LLM to generate a targeted "verification" search query that
    /// is designed to find evidence resolving the most critical contradiction.
    /// </summary>
    private async Task<string> GenerateTieBreakerQueryAsync(
        ResearchState state, CancellationToken ct)
    {
        var highConflicts = state.Contradictions
            .Where(c => c.Severity == ContradictionSeverity.High)
            .Take(3)
            .ToList();

        if (highConflicts.Count == 0)
            return $"{state.CurrentQuery} latest verified data";

        var conflictsJson = JsonSerializer.Serialize(highConflicts);

        const string systemPrompt =
            "You are a research verification specialist. Given a list of contradictory claims, " +
            "generate a single, precise web-search query (max 20 words) that would find a " +
            "third-party authoritative source to resolve the main conflict. " +
            "Respond with ONLY the query string, no JSON wrapper.";

        var userMessage =
            $"Contradictions to resolve:\n{conflictsJson}\n\n" +
            $"Original research topic: \"{state.CurrentQuery}\"";

        // For tie-breaker queries we want plain text, not JSON; use a small workaround.
        var response = await _llm.CompleteJsonAsync(
            "Respond with JSON: {\"query\": \"<your query here>\"}",
            $"{systemPrompt}\n\n{userMessage}",
            ct);

        try
        {
            using var doc = JsonDocument.Parse(response);
            if (doc.RootElement.TryGetProperty("query", out var q))
                return q.GetString() ?? $"Verification: {state.CurrentQuery}";
        }
        catch { /* fall through */ }

        return $"Verification: {state.CurrentQuery} conflicting evidence";
    }

    public void Dispose()
    {
        _scout.Dispose();
        _llm.Dispose();
    }
}
