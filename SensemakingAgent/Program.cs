// Program.cs
// Entry point for the Autonomous Sensemaking Research Agent.
//
// Usage:
//   dotnet run -- "The impact of solid-state batteries on the EV supply chain"
//
// Environment variables:
//   OPENAI_API_KEY    – required for Analyst, Critic and Writer nodes.
//   TAVILY_API_KEY    – optional; enables rich Tavily search (fallback: DuckDuckGo).
//   OPENAI_BASE_URL   – optional; override for Azure OpenAI or compatible endpoints.
//   OPENAI_MODEL      – optional; defaults to "gpt-4o".
//   SCRAPER_MAX_RESULTS – optional; max search results per query (default 5).

using SensemakingAgent;

// ── Banner ────────────────────────────────────────────────────────────────
Console.WriteLine();
Console.WriteLine("╔═══════════════════════════════════════════════════════╗");
Console.WriteLine("║   Autonomous Sensemaking Research Agent  v1.0        ║");
Console.WriteLine("║   https://github.com/lishuren/                       ║");
Console.WriteLine("║   AI-Driven-Autonomous-Sensemaking-Research-Agent    ║");
Console.WriteLine("╚═══════════════════════════════════════════════════════╝");
Console.WriteLine();

// ── Query ─────────────────────────────────────────────────────────────────
string query;

if (args.Length > 0)
{
    query = string.Join(" ", args).Trim();
}
else
{
    Console.Write("Enter your research query: ");
    query = Console.ReadLine()?.Trim() ?? string.Empty;
}

if (string.IsNullOrWhiteSpace(query))
{
    Console.Error.WriteLine("Error: research query cannot be empty.");
    Environment.Exit(1);
}

// ── Run ───────────────────────────────────────────────────────────────────
using var cts = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) =>
{
    e.Cancel = true;
    Console.WriteLine("\n[Main] Cancellation requested…");
    cts.Cancel();
};

using var graph = new SensemakingGraph();

try
{
    var (brief, finalState) = await graph.RunAsync(query, cts.Token);

    // ── Print brief ───────────────────────────────────────────────────────
    brief.PrintToConsole();

    // ── Visualise ─────────────────────────────────────────────────────────
    const string htmlPath = "knowledge_graph.html";
    Visualizer.GenerateHtml(finalState, htmlPath);

    Console.WriteLine();
    Console.WriteLine($"Open '{htmlPath}' in a browser to explore the interactive graph.");
}
catch (OperationCanceledException)
{
    Console.WriteLine("[Main] Run cancelled by user.");
    Environment.Exit(1);
}
catch (Exception ex)
{
    Console.Error.WriteLine($"[Main] Fatal error: {ex.Message}");
    Console.Error.WriteLine(ex.StackTrace);
    Environment.Exit(2);
}
