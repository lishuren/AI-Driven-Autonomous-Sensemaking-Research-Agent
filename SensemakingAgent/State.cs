// State.cs
// Defines the ResearchState that flows through the Sensemaking agent loop.
// Each field uses an explicit merge strategy so that data accumulates across iterations
// rather than being overwritten — mirroring LangGraph's operator.add pattern.
//
// Reference: https://github.com/lishuren/AI-Driven-Autonomous-Research-Agent

using System.Text.Json.Serialization;

namespace SensemakingAgent;

// ---------------------------------------------------------------------------
// Value types
// ---------------------------------------------------------------------------

/// <summary>A single web-scraped document returned by <see cref="ResearchScraper"/>.</summary>
public sealed record ScrapedDocument(
    string Url,
    string Title,
    string RawContent
);

/// <summary>
/// A Subject → Predicate → Object triplet extracted from scraped text.
/// <paramref name="Evidence"/> holds the source sentence that supports the claim.
/// </summary>
public sealed record Triplet(
    string Subject,
    string Predicate,
    string Object,
    string Evidence,
    string SourceUrl = ""
);

/// <summary>A contradiction detected between two claims in the research corpus.</summary>
public sealed record Contradiction(
    string ClaimA,
    string ClaimB,
    string SourceA,
    string SourceB,
    ContradictionSeverity Severity
);

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum ContradictionSeverity
{
    Low,
    High
}

// ---------------------------------------------------------------------------
// Knowledge Graph
// ---------------------------------------------------------------------------

/// <summary>
/// In-memory relational model built during the research loop.
/// Entities are nodes; Triplets are directed, labelled edges.
/// </summary>
public sealed class KnowledgeGraph
{
    public List<string> Entities { get; init; } = [];
    public List<Triplet> Triplets { get; init; } = [];

    /// <summary>
    /// Merge <paramref name="other"/> into this graph.
    /// New entities and triplets are appended; exact duplicates (same Subject, Predicate,
    /// Object <em>and</em> SourceUrl) are removed so that the same claim from multiple
    /// independent sources is still preserved as separate, traceable entries.
    /// </summary>
    public KnowledgeGraph Merge(KnowledgeGraph other)
    {
        var mergedEntities = Entities
            .Concat(other.Entities)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var mergedTriplets = Triplets
            .Concat(other.Triplets)
            .GroupBy(
                t => (t.Subject.ToLowerInvariant(),
                      t.Predicate.ToLowerInvariant(),
                      t.Object.ToLowerInvariant(),
                      t.SourceUrl.ToLowerInvariant()))
            .Select(g => g.First())
            .ToList();

        return new KnowledgeGraph
        {
            Entities = mergedEntities,
            Triplets = mergedTriplets
        };
    }

    /// <summary>Returns the number of distinct nodes that appear in at least one triplet.</summary>
    public int ActiveNodeCount =>
        Triplets
            .SelectMany(t => new[] { t.Subject, t.Object })
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Count();
}

// ---------------------------------------------------------------------------
// Research State
// ---------------------------------------------------------------------------

/// <summary>
/// The canonical shared state passed between every node in the Sensemaking graph.
/// Create a new <see cref="ResearchState"/> with <see cref="Create"/> and apply
/// incremental updates via <see cref="ApplyUpdate"/>.
/// </summary>
public sealed class ResearchState
{
    // ---- Accumulated data (append-only, like operator.add in Python LangGraph) ----

    /// <summary>Raw documents collected by the Scout (ResearchScraper).</summary>
    public IReadOnlyList<ScrapedDocument> Documents { get; private set; } = [];

    /// <summary>Growing relational map of entities and their relationships.</summary>
    public KnowledgeGraph KnowledgeGraph { get; private set; } = new();

    /// <summary>Contradictions detected by the Critic node.</summary>
    public IReadOnlyList<Contradiction> Contradictions { get; private set; } = [];

    /// <summary>
    /// Open questions / unknown terms that require recursive sub-searches.
    /// Populated by the Critic; consumed by the Scout.
    /// </summary>
    public IReadOnlyList<string> ResearchGaps { get; private set; } = [];

    // ---- Scalar state ----

    /// <summary>The query the Scout will use on its next run.</summary>
    public string CurrentQuery { get; private set; } = string.Empty;

    /// <summary>Number of Scout→Analyst→Critic loops completed so far.</summary>
    public int IterationCount { get; private set; }

    /// <summary>
    /// Number of triplets present at the <em>start</em> of the current iteration,
    /// used to calculate graph-saturation (growth rate).
    /// </summary>
    public int TripletCountAtIterationStart { get; private set; }

    /// <summary>
    /// Set to <see langword="true"/> once a Tie-Breaker search has been dispatched
    /// for the current high-severity contradiction, preventing infinite loops.
    /// </summary>
    public bool TieBreakerDispatched { get; private set; }

    // ---- Factory ----

    public static ResearchState Create(string initialQuery) =>
        new() { CurrentQuery = initialQuery };

    // ---- Immutable update helpers (return new state) ----

    /// <summary>
    /// Returns a new <see cref="ResearchState"/> with the supplied delta merged in.
    /// Fields left <see langword="null"/> in the delta are carried forward unchanged.
    /// </summary>
    public ResearchState ApplyUpdate(ResearchStateUpdate delta)
    {
        var next = (ResearchState)MemberwiseClone();

        if (delta.NewDocuments is { Count: > 0 })
            next.Documents = [.. Documents, .. delta.NewDocuments];

        if (delta.NewKnowledgeGraph is not null)
            next.KnowledgeGraph = KnowledgeGraph.Merge(delta.NewKnowledgeGraph);

        if (delta.NewContradictions is { Count: > 0 })
            next.Contradictions = [.. Contradictions, .. delta.NewContradictions];

        if (delta.NewResearchGaps is { Count: > 0 })
            next.ResearchGaps = [.. ResearchGaps, .. delta.NewResearchGaps];

        // Resolve gaps that have been addressed
        if (delta.ResolvedGaps is { Count: > 0 })
            next.ResearchGaps = next.ResearchGaps
                .Where(g => !delta.ResolvedGaps.Contains(g, StringComparer.OrdinalIgnoreCase))
                .ToList();

        if (delta.CurrentQuery is not null)
            next.CurrentQuery = delta.CurrentQuery;

        if (delta.IncrementIteration)
        {
            next.TripletCountAtIterationStart = next.KnowledgeGraph.Triplets.Count;
            next.IterationCount = IterationCount + 1;
        }

        if (delta.TieBreakerDispatched.HasValue)
            next.TieBreakerDispatched = delta.TieBreakerDispatched.Value;

        return next;
    }

    // ---- Helpers ----

    /// <summary>
    /// Returns <see langword="true"/> if the graph grew by more than 10 % in this iteration.
    /// Used by <see cref="SensemakingGraph"/> to detect saturation.
    /// </summary>
    public bool GraphGrewSignificantly()
    {
        int current = KnowledgeGraph.Triplets.Count;
        if (TripletCountAtIterationStart == 0)
            return current > 0;

        double growth = (double)(current - TripletCountAtIterationStart) / TripletCountAtIterationStart;
        return growth > 0.10;
    }
}

/// <summary>
/// Partial state update returned by each node.
/// <see langword="null"/> / empty fields are ignored during merge.
/// </summary>
public sealed class ResearchStateUpdate
{
    public IReadOnlyList<ScrapedDocument>? NewDocuments { get; init; }
    public KnowledgeGraph? NewKnowledgeGraph { get; init; }
    public IReadOnlyList<Contradiction>? NewContradictions { get; init; }
    public IReadOnlyList<string>? NewResearchGaps { get; init; }
    public IReadOnlyList<string>? ResolvedGaps { get; init; }
    public string? CurrentQuery { get; init; }
    public bool IncrementIteration { get; init; }
    public bool? TieBreakerDispatched { get; init; }
}
