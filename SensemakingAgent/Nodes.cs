// Nodes.cs
// Defines the three intelligence nodes that operate on ResearchState:
//
//   AnalystNode  – extracts entities and triplets from raw documents using an LLM.
//   CriticNode   – detects contradictions and research gaps across all triplets.
//   WriterNode   – synthesizes the Knowledge Graph into a structured research brief.
//
// Each node takes the current ResearchState and returns a ResearchStateUpdate
// (the partial-state delta pattern used by LangGraph).
//
// LLM back-end: OpenAI Chat Completions (JSON mode).
// Set OPENAI_API_KEY in the environment; the base URL can be overridden via
// OPENAI_BASE_URL for Azure OpenAI or compatible endpoints.

using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SensemakingAgent;

// ---------------------------------------------------------------------------
// LLM client helpers
// ---------------------------------------------------------------------------

public sealed record LlmConfig(
    string ApiKey,
    string BaseUrl = "https://api.openai.com/v1",
    string Model = "gpt-4o"
)
{
    public static LlmConfig FromEnvironment() => new(
        ApiKey: Environment.GetEnvironmentVariable("OPENAI_API_KEY") ?? string.Empty,
        BaseUrl: Environment.GetEnvironmentVariable("OPENAI_BASE_URL")
                 ?? "https://api.openai.com/v1",
        Model: Environment.GetEnvironmentVariable("OPENAI_MODEL") ?? "gpt-4o"
    );
}

file sealed record ChatMessage(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("content")] string Content
);

file sealed record ChatRequest(
    [property: JsonPropertyName("model")] string Model,
    [property: JsonPropertyName("messages")] List<ChatMessage> Messages,
    [property: JsonPropertyName("response_format")] JsonElement ResponseFormat,
    [property: JsonPropertyName("temperature")] double Temperature = 0.2
);

file sealed record ChatChoice(
    [property: JsonPropertyName("message")] ChatMessage Message
);

file sealed record ChatResponse(
    [property: JsonPropertyName("choices")] List<ChatChoice> Choices
);

// ---------------------------------------------------------------------------
// Analyst DTOs (LLM structured output)
// ---------------------------------------------------------------------------

file sealed record AnalystOutput(
    [property: JsonPropertyName("entities")] List<string> Entities,
    [property: JsonPropertyName("triplets")] List<TripletDto> Triplets
);

file sealed record TripletDto(
    [property: JsonPropertyName("subject")] string Subject,
    [property: JsonPropertyName("predicate")] string Predicate,
    [property: JsonPropertyName("object")] string Object,
    [property: JsonPropertyName("evidence")] string Evidence,
    [property: JsonPropertyName("source_url")] string SourceUrl = ""
);

// ---------------------------------------------------------------------------
// Critic DTOs
// ---------------------------------------------------------------------------

file sealed record CriticOutput(
    [property: JsonPropertyName("contradictions")] List<ContradictionDto> Contradictions,
    [property: JsonPropertyName("research_gaps")] List<string> ResearchGaps
);

file sealed record ContradictionDto(
    [property: JsonPropertyName("claim_a")] string ClaimA,
    [property: JsonPropertyName("claim_b")] string ClaimB,
    [property: JsonPropertyName("source_a")] string SourceA,
    [property: JsonPropertyName("source_b")] string SourceB,
    [property: JsonPropertyName("severity")] string Severity
);

// ---------------------------------------------------------------------------
// Shared LLM gateway
// ---------------------------------------------------------------------------

public sealed class LlmGateway : IDisposable
{
    private readonly LlmConfig _cfg;
    private readonly HttpClient _http;
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web);

    private static readonly JsonElement JsonModeFormat =
        JsonDocument.Parse("""{"type":"json_object"}""").RootElement.Clone();

    public LlmGateway(LlmConfig? config = null, HttpClient? httpClient = null)
    {
        _cfg = config ?? LlmConfig.FromEnvironment();
        _http = httpClient ?? new HttpClient { Timeout = TimeSpan.FromSeconds(120) };

        if (!string.IsNullOrWhiteSpace(_cfg.ApiKey))
            _http.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("Bearer", _cfg.ApiKey);
    }

    public async Task<string> CompleteJsonAsync(
        string systemPrompt, string userMessage, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(_cfg.ApiKey))
        {
            Console.Error.WriteLine("[LLM] OPENAI_API_KEY not set – returning empty JSON.");
            return "{}";
        }

        var request = new ChatRequest(
            Model: _cfg.Model,
            Messages:
            [
                new("system", systemPrompt),
                new("user", userMessage)
            ],
            ResponseFormat: JsonModeFormat
        );

        var url = $"{_cfg.BaseUrl.TrimEnd('/')}/chat/completions";
        using var response = await _http.PostAsJsonAsync(url, request, JsonOpts, ct);
        response.EnsureSuccessStatusCode();

        var result = await response.Content.ReadFromJsonAsync<ChatResponse>(JsonOpts, ct);
        return result?.Choices.FirstOrDefault()?.Message.Content ?? "{}";
    }

    public void Dispose() => _http.Dispose();
}

// ---------------------------------------------------------------------------
// AnalystNode
// ---------------------------------------------------------------------------

/// <summary>
/// Reads the latest batch of <see cref="ScrapedDocument"/>s from the state,
/// calls the LLM to extract entities and relationship triplets, and returns
/// a <see cref="ResearchStateUpdate"/> that grows the Knowledge Graph.
/// </summary>
public sealed class AnalystNode
{
    private const string SystemPrompt = """
        ### SYSTEM PROMPT: Research Analyst (Knowledge Graph Specialist)

        ROLE
        You are a Senior Research Analyst specialising in Relationship Extraction and Synthesis.
        Transform unstructured web-scraped text into a structured Knowledge Graph.

        OBJECTIVES
        1. Identify Entities: Extract key Nodes (Organisations, People, Technologies,
           Regulatory Bodies, Concepts, Market Trends).
        2. Define Relationships: Map directed Edges using active-verb predicates
           (e.g. "accelerates", "inhibits", "funds", "is-a-version-of").
        3. Cross-document Links: If the same entity appears in multiple documents,
           connect it to entities from other documents where a logical relationship exists.

        EXTRACTION GUIDELINES
        - Precision: Use specific terms (e.g. "Transformer Architecture", "GDPR Compliance"),
          not generic ones like "Data" or "Technology".
        - Normalisation: Resolve aliases ("OpenAI" and "OAI" → "OpenAI").
        - Sensemaking: Infer hidden connections (e.g. Lithium Shortage → delays → EV Production).
        - Source URL: Set "source_url" to the URL of the document the triplet was extracted from.

        OUTPUT FORMAT (STRICT JSON)
        {
          "entities": ["Entity1", "Entity2", ...],
          "triplets": [
            { "subject": "...", "predicate": "...", "object": "...", "evidence": "...", "source_url": "https://..." }
          ]
        }
        """;

    private readonly LlmGateway _llm;

    public AnalystNode(LlmGateway? llm = null)
    {
        _llm = llm ?? new LlmGateway();
    }

    public async Task<ResearchStateUpdate> RunAsync(
        ResearchState state, CancellationToken ct = default)
    {
        if (state.Documents.Count == 0)
            return new ResearchStateUpdate();

        // Feed only documents added in the current iteration (last N docs).
        var batch = state.Documents
            .TakeLast(Math.Min(state.Documents.Count, 5))
            .ToList();

        var sb = new StringBuilder();
        sb.AppendLine("Extract entities and triplets from the following documents.");
        sb.AppendLine();

        foreach (var doc in batch)
        {
            sb.AppendLine($"## SOURCE: {doc.Url}");
            sb.AppendLine($"### {doc.Title}");
            // Truncate very long content to keep within token limits.
            var content = doc.RawContent.Length > 3000
                ? doc.RawContent[..3000] + " [truncated]"
                : doc.RawContent;
            sb.AppendLine(content);
            sb.AppendLine();
        }

        string json = await _llm.CompleteJsonAsync(SystemPrompt, sb.ToString(), ct);

        AnalystOutput? output;
        try
        {
            output = JsonSerializer.Deserialize<AnalystOutput>(
                json, new JsonSerializerOptions(JsonSerializerDefaults.Web));
        }
        catch (JsonException ex)
        {
            Console.Error.WriteLine($"[Analyst] JSON parse error: {ex.Message}");
            return new ResearchStateUpdate();
        }

        if (output is null) return new ResearchStateUpdate();

        var triplets = output.Triplets
            .Select(t => new Triplet(t.Subject, t.Predicate, t.Object, t.Evidence, t.SourceUrl))
            .ToList();

        var graph = new KnowledgeGraph
        {
            Entities = [.. output.Entities],
            Triplets = triplets
        };

        Console.WriteLine($"[Analyst] Extracted {triplets.Count} triplets, " +
                          $"{output.Entities.Count} entities.");

        return new ResearchStateUpdate { NewKnowledgeGraph = graph };
    }
}

// ---------------------------------------------------------------------------
// CriticNode
// ---------------------------------------------------------------------------

/// <summary>
/// Compares incoming triplets against the existing Knowledge Graph to detect
/// factual contradictions and identify unknown terms that require recursive search.
/// </summary>
public sealed class CriticNode
{
    private const string SystemPrompt = """
        ### SYSTEM PROMPT: Research Critic (Dialectical Reasoner)

        ROLE
        You are a rigorous fact-checker and gap-detector. You receive:
        1. A list of EXISTING triplets already in the Knowledge Graph.
        2. A list of NEW triplets just extracted from the latest documents.

        TASKS
        A. Contradictions: For every new triplet that conflicts with an existing one
           (different values for the same subject-predicate pair, opposing directional
           claims, conflicting dates or statistics), record a contradiction entry.
           Mark severity as "High" if the conflict is direct and factual, "Low" if
           circumstantial or interpretive.
        B. Research Gaps: Identify entities or concepts mentioned in the new triplets
           that are poorly defined or unexplained (jargon, acronyms, foundational
           concepts assumed without elaboration). Output each as a short question.

        OUTPUT FORMAT (STRICT JSON)
        {
          "contradictions": [
            {
              "claim_a": "...", "source_a": "...",
              "claim_b": "...", "source_b": "...",
              "severity": "High" | "Low"
            }
          ],
          "research_gaps": ["What is X?", "Explain Y in context Z", ...]
        }
        """;

    private readonly LlmGateway _llm;

    public CriticNode(LlmGateway? llm = null)
    {
        _llm = llm ?? new LlmGateway();
    }

    public async Task<ResearchStateUpdate> RunAsync(
        ResearchState state, CancellationToken ct = default)
    {
        if (state.KnowledgeGraph.Triplets.Count == 0)
            return new ResearchStateUpdate();

        var existingJson = JsonSerializer.Serialize(
            state.KnowledgeGraph.Triplets.Take(50),
            new JsonSerializerOptions { WriteIndented = false });

        var newTriplets = state.KnowledgeGraph.Triplets
            .TakeLast(Math.Min(state.KnowledgeGraph.Triplets.Count, 20))
            .ToList();

        var newJson = JsonSerializer.Serialize(
            newTriplets,
            new JsonSerializerOptions { WriteIndented = false });

        var userMessage =
            $"EXISTING TRIPLETS:\n{existingJson}\n\nNEW TRIPLETS:\n{newJson}";

        string json = await _llm.CompleteJsonAsync(SystemPrompt, userMessage, ct);

        CriticOutput? output;
        try
        {
            output = JsonSerializer.Deserialize<CriticOutput>(
                json, new JsonSerializerOptions(JsonSerializerDefaults.Web));
        }
        catch (JsonException ex)
        {
            Console.Error.WriteLine($"[Critic] JSON parse error: {ex.Message}");
            return new ResearchStateUpdate();
        }

        if (output is null) return new ResearchStateUpdate();

        var contradictions = output.Contradictions
            .Select(c => new Contradiction(
                c.ClaimA, c.ClaimB, c.SourceA, c.SourceB,
                Enum.TryParse<ContradictionSeverity>(c.Severity, true, out var sev)
                    ? sev : ContradictionSeverity.Low))
            .ToList();

        Console.WriteLine(
            $"[Critic] Found {contradictions.Count} contradiction(s), " +
            $"{output.ResearchGaps.Count} gap(s).");

        return new ResearchStateUpdate
        {
            NewContradictions = contradictions,
            NewResearchGaps = output.ResearchGaps
        };
    }
}

// ---------------------------------------------------------------------------
// WriterNode
// ---------------------------------------------------------------------------

/// <summary>
/// Synthesizes the completed Knowledge Graph and Contradiction Log into a
/// structured research brief.  The report is graph-driven, not text-driven.
/// </summary>
public sealed class WriterNode
{
    private const string SystemPromptTemplate = """
        ### SYSTEM PROMPT: Executive Synthesizer (Graph-to-Narrative)

        ROLE
        You are a Strategic Advisor. Synthesise the Knowledge Graph and Contradiction Log
        into a high-level Research Brief.

        INPUT DATA
        - Entities: {ENTITIES}
        - Triplets (The Map): {TRIPLETS}
        - Unresolved Contradictions: {CONTRADICTIONS}

        REPORT STRUCTURE
        1. Executive Summary: A 3-sentence "bottom line up front" (BLUF).
        2. The Knowledge Map: Describe the core relationship between the 3 most connected entities.
           Example: "Entity A acts as a bottleneck for Entity B, which is being disrupted by Trend C."
        3. Key Pillars: Group related triplets into 3 thematic "pillars" of research.
        4. Critical Uncertainties (Sensemaking Edge): List contradictions and explain why sources
           might disagree (market scope, time horizon, methodology differences).
        5. Strategic Gaps: What does the graph suggest is missing or worth investigating next?

        STRICT RULES
        - No Hallucinations: Every claim must be traceable to a triplet.
        - Relational Language: Use verbs that describe influence (drives, impedes, correlates with).
        - Clarity: Bold **Entities** to make the report scannable.

        OUTPUT FORMAT (STRICT JSON)
        {
          "executive_summary": "...",
          "knowledge_map": "...",
          "key_pillars": ["Pillar 1: ...", "Pillar 2: ...", "Pillar 3: ..."],
          "critical_uncertainties": ["..."],
          "strategic_gaps": ["..."]
        }
        """;

    private readonly LlmGateway _llm;

    public WriterNode(LlmGateway? llm = null)
    {
        _llm = llm ?? new LlmGateway();
    }

    public async Task<ResearchBrief> RunAsync(
        ResearchState state, CancellationToken ct = default)
    {
        var entitiesJson = JsonSerializer.Serialize(state.KnowledgeGraph.Entities);
        var tripletsJson = JsonSerializer.Serialize(state.KnowledgeGraph.Triplets);
        var contradictionsJson = JsonSerializer.Serialize(state.Contradictions);

        var systemPrompt = SystemPromptTemplate
            .Replace("{ENTITIES}", entitiesJson)
            .Replace("{TRIPLETS}", tripletsJson)
            .Replace("{CONTRADICTIONS}", contradictionsJson);

        var userMessage =
            $"Research topic: \"{state.CurrentQuery}\"\n\n" +
            $"Iterations completed: {state.IterationCount}\n" +
            $"Total triplets: {state.KnowledgeGraph.Triplets.Count}\n" +
            $"Total contradictions: {state.Contradictions.Count}";

        string json = await _llm.CompleteJsonAsync(systemPrompt, userMessage, ct);

        try
        {
            var brief = JsonSerializer.Deserialize<ResearchBrief>(
                json, new JsonSerializerOptions(JsonSerializerDefaults.Web));
            return brief ?? ResearchBrief.Empty;
        }
        catch (JsonException ex)
        {
            Console.Error.WriteLine($"[Writer] JSON parse error: {ex.Message}");
            return ResearchBrief.Empty;
        }
    }
}

// ---------------------------------------------------------------------------
// ResearchBrief (final output)
// ---------------------------------------------------------------------------

/// <summary>Structured final output generated by <see cref="WriterNode"/>.</summary>
public sealed record ResearchBrief(
    [property: JsonPropertyName("executive_summary")] string ExecutiveSummary,
    [property: JsonPropertyName("knowledge_map")] string KnowledgeMap,
    [property: JsonPropertyName("key_pillars")] List<string> KeyPillars,
    [property: JsonPropertyName("critical_uncertainties")] List<string> CriticalUncertainties,
    [property: JsonPropertyName("strategic_gaps")] List<string> StrategicGaps
)
{
    public static ResearchBrief Empty => new(
        string.Empty, string.Empty, [], [], []);

    public void PrintToConsole()
    {
        Console.WriteLine();
        Console.WriteLine("═══════════════════════════════════════════════════════");
        Console.WriteLine("  AUTONOMOUS SENSEMAKING RESEARCH BRIEF");
        Console.WriteLine("═══════════════════════════════════════════════════════");
        Console.WriteLine();
        Console.WriteLine("── EXECUTIVE SUMMARY ──────────────────────────────────");
        Console.WriteLine(ExecutiveSummary);
        Console.WriteLine();
        Console.WriteLine("── KNOWLEDGE MAP ───────────────────────────────────────");
        Console.WriteLine(KnowledgeMap);
        Console.WriteLine();
        Console.WriteLine("── KEY PILLARS ─────────────────────────────────────────");
        foreach (var pillar in KeyPillars)
            Console.WriteLine($"  • {pillar}");
        Console.WriteLine();
        Console.WriteLine("── CRITICAL UNCERTAINTIES ──────────────────────────────");
        foreach (var u in CriticalUncertainties)
            Console.WriteLine($"  ⚠  {u}");
        Console.WriteLine();
        Console.WriteLine("── STRATEGIC GAPS ──────────────────────────────────────");
        foreach (var g in StrategicGaps)
            Console.WriteLine($"  → {g}");
        Console.WriteLine();
        Console.WriteLine("═══════════════════════════════════════════════════════");
    }
}
