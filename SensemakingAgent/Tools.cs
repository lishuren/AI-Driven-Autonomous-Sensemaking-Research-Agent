// Tools.cs
// ResearchScraper: Scout layer that fetches raw content for a given query.
//
// Adapts the search and scraping logic from:
//   https://github.com/lishuren/AI-Driven-Autonomous-Research-Agent
// into a clean, async, stateless class that returns structured ScrapedDocument records.
//
// Supported back-ends (selected by configuration):
//   1. TavilySearch  – structured AI-powered web search (preferred)
//   2. HttpClient    – fallback direct HTTP fetch with basic HTML text extraction

using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace SensemakingAgent;

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/// <summary>Connection settings injected via environment variables or appsettings.</summary>
public sealed record ScraperConfig(
    string TavilyApiKey,
    int MaxResultsPerQuery = 5,
    int HttpTimeoutSeconds = 30
)
{
    public static ScraperConfig FromEnvironment() => new(
        TavilyApiKey: Environment.GetEnvironmentVariable("TAVILY_API_KEY") ?? string.Empty,
        MaxResultsPerQuery: int.TryParse(
            Environment.GetEnvironmentVariable("SCRAPER_MAX_RESULTS"), out int n) ? n : 5
    );
}

// ---------------------------------------------------------------------------
// Tavily response DTOs
// ---------------------------------------------------------------------------

file sealed record TavilyRequest(
    [property: JsonPropertyName("api_key")] string ApiKey,
    [property: JsonPropertyName("query")] string Query,
    [property: JsonPropertyName("max_results")] int MaxResults,
    [property: JsonPropertyName("include_raw_content")] bool IncludeRawContent = true
);

file sealed record TavilyResponse(
    [property: JsonPropertyName("results")] List<TavilyResult> Results
);

file sealed record TavilyResult(
    [property: JsonPropertyName("url")] string Url,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("content")] string Content,
    [property: JsonPropertyName("raw_content")] string? RawContent
);

// ---------------------------------------------------------------------------
// ResearchScraper
// ---------------------------------------------------------------------------

/// <summary>
/// Stateless Scout component.
/// Call <see cref="RunSearchAsync"/> to retrieve a structured list of web documents
/// for the given query.
/// </summary>
public sealed class ResearchScraper : IDisposable
{
    private const string TavilyEndpoint = "https://api.tavily.com/search";
    private const string UserAgent =
        "Mozilla/5.0 (compatible; SensemakingAgent/1.0; +https://github.com/lishuren/AI-Driven-Autonomous-Sensemaking-Research-Agent)";

    private readonly ScraperConfig _config;
    private readonly HttpClient _http;
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web);

    public ResearchScraper(ScraperConfig config, HttpClient? httpClient = null)
    {
        _config = config;
        _http = httpClient ?? BuildDefaultHttpClient(config.HttpTimeoutSeconds);
    }

    // ---- Public API ----

    /// <summary>
    /// Searches the web for <paramref name="query"/> and returns structured documents.
    /// Uses Tavily if an API key is configured; otherwise falls back to DuckDuckGo HTML scraping.
    /// </summary>
    public async Task<List<ScrapedDocument>> RunSearchAsync(
        string query, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(query))
            return [];

        return string.IsNullOrWhiteSpace(_config.TavilyApiKey)
            ? await FallbackSearchAsync(query, ct)
            : await TavilySearchAsync(query, ct);
    }

    // ---- Tavily back-end ----

    private async Task<List<ScrapedDocument>> TavilySearchAsync(
        string query, CancellationToken ct)
    {
        var body = new TavilyRequest(
            _config.TavilyApiKey, query, _config.MaxResultsPerQuery);

        using var response = await _http.PostAsJsonAsync(TavilyEndpoint, body, JsonOpts, ct);
        response.EnsureSuccessStatusCode();

        var result = await response.Content.ReadFromJsonAsync<TavilyResponse>(JsonOpts, ct);
        if (result?.Results is null)
            return [];

        return result.Results
            .Select(r => new ScrapedDocument(
                Url: r.Url,
                Title: r.Title,
                RawContent: r.RawContent ?? r.Content))
            .ToList();
    }

    // ---- HTTP fallback back-end ----

    /// <summary>
    /// Minimal fallback: queries DuckDuckGo's lite HTML interface and returns
    /// the first <see cref="ScraperConfig.MaxResultsPerQuery"/> result snippets.
    /// </summary>
    private async Task<List<ScrapedDocument>> FallbackSearchAsync(
        string query, CancellationToken ct)
    {
        var encoded = Uri.EscapeDataString(query);
        var url = $"https://html.duckduckgo.com/html/?q={encoded}";

        string html;
        try
        {
            html = await _http.GetStringAsync(url, ct);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[Scraper] Fallback fetch failed: {ex.Message}");
            return [];
        }

        return ParseDuckDuckGoHtml(html, _config.MaxResultsPerQuery);
    }

    // ---- HTML parsing helpers ----

    private static List<ScrapedDocument> ParseDuckDuckGoHtml(string html, int max)
    {
        var docs = new List<ScrapedDocument>();

        // Very lightweight extraction – no full HTML parser dependency required.
        var resultBlocks = Regex.Matches(
            html,
            @"<a[^>]+class=""result__a""[^>]+href=""([^""]+)""[^>]*>(.*?)</a>.*?" +
            @"<a[^>]+class=""result__snippet""[^>]*>(.*?)</a>",
            RegexOptions.Singleline | RegexOptions.IgnoreCase);

        foreach (Match m in resultBlocks)
        {
            if (docs.Count >= max) break;

            string href = HtmlDecode(m.Groups[1].Value.Trim());
            string title = StripTags(m.Groups[2].Value);
            string snippet = StripTags(m.Groups[3].Value);

            if (string.IsNullOrWhiteSpace(href)) continue;

            docs.Add(new ScrapedDocument(href, title, snippet));
        }

        return docs;
    }

    private static string StripTags(string html) =>
        Regex.Replace(html, "<[^>]+>", string.Empty).Trim();

    private static string HtmlDecode(string text) =>
        System.Net.WebUtility.HtmlDecode(text);

    // ---- Factory helpers ----

    private static HttpClient BuildDefaultHttpClient(int timeoutSeconds)
    {
        var client = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(timeoutSeconds)
        };
        client.DefaultRequestHeaders.UserAgent.ParseAdd(UserAgent);
        client.DefaultRequestHeaders.Accept.Add(
            new MediaTypeWithQualityHeaderValue("application/json"));
        return client;
    }

    public void Dispose() => _http.Dispose();
}
