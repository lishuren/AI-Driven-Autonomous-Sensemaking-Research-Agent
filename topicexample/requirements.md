# Maintaining a Legacy .NET C# Product Without Upgrading

## Topic

How to maintain a very old .NET C# product without upgrading the framework —
a comprehensive guide for software developers.

## Research Focus

Prioritize concrete, actionable guidance grounded in:

1. Microsoft official documentation and support lifecycle statements
2. Practitioner blog posts and StackOverflow discussions from experienced
   .NET developers
3. Security advisories from NIST/CVE and Microsoft Security Response Center
4. Real-world patterns: NuGet lock files, web.config hardening, IIS / Windows
   Service deployment hardening

Prefer specific tool names, version numbers, and policy references over
generic best-practice categories.

## Background

Many organizations run business-critical software on legacy .NET Framework
versions (2.0, 3.5, 4.0, 4.5, 4.6). Upgrading is often not viable due to
dependency lock-in, third-party component abandonment, or contractual
obligations. The challenge is keeping the application stable, secure, and
understandable over a multi-year horizon without touching the core framework.

Key concerns to research:

- **Environment freezing** — isolating the app from OS and infrastructure drift
  (VM/container strategies, artifact archiving, dedicated build server)
- **Code stabilization** — characterization testing, judicious refactoring,
  static analysis without touching the framework
- **Security hardening** — patching without upgrading (network isolation,
  dependency audits, OS support lifecycle)
- **Integration strategies** — API wrappers, Strangler Fig pattern, sidecar
  services in modern .NET 8/9 that talk to the legacy core
- **Operational practices** — monitoring, database maintenance, documentation
  of "tribal knowledge"
- **Tooling** — which tools (NDepend, dotPeek, Roslyn analyzers, ILSpy) are
  safe to use against old TFM targets
- **Known vulnerabilities** — CVEs and advisory mitigations specific to old
  .NET Framework releases
