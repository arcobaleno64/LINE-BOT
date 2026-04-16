# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Consider future features and enhancements here

### Changed
- Updates to existing functionality

### Deprecated
- Feature deprecation notices

### Removed
- Removed functionality

### Fixed
- Bug fixes and corrections

### Security
- Security-related changes

---

## [1.0.0] - 2026-04-16

### Added
- **Multi-Provider AI Integration**: Gemini → OpenAI → Claude failover with intelligent fallback mechanism
- **LINE Message Handling**: Complete support for text, image, and file messages with context-aware routing
- **Document Processing Pipeline**: Support for .txt, .md, .csv, .json, .xml, .log, .pdf, .docx, .xlsx, .pptx file formats
- **Mention Gate System**: Smart mention detection for group and room conversations (requires @bot mention for text messages)
- **Background Queue Processing**: Bounded channel-based async processing with 256-item capacity and hosted worker service
- **Request Optimization**: Response caching service, in-flight request merge, and 429 backoff handling
- **Webhook Security**: LINE signature verification (`x-line-signature`) with secure token management
- **Observability & Monitoring**: Health checks, readiness probes with queue status, and metrics tracking
- **File Download Endpoint**: Secure file downloads with 24-hour expiring tokens
- **Conversation History**: Per-user/group conversation tracking with summary generation
- **GitHub Actions CI/CD**: Automated testing, Docker build, and Render deployment pipeline
- **Comprehensive Test Suite**: 150+ unit and integration tests with xUnit
- **Complete Documentation**: README (EN/ZH-TW), user guide, deployment manual, and design review docs

### Technical Details
- **Framework**: ASP.NET Core 10 (.NET 10)
- **Queue System**: `System.Threading.Channels.Channel<T>` with `BoundedChannelOptions`
- **Document Handling**: `DocumentFormat.OpenXml` for Office format parsing
- **AI Services**: Multi-provider with configurable fallback order and rate limiting
- **Deployment**: Docker containerization with Render cloud platform support

### Known Limitations (by Design)
- File downloads available only in user-to-user conversations
- Image message handling defaults to user-to-user (configurable for groups via `App:AllowGroupFileHandling`)
- Text messages in groups/rooms require bot mention (Mention Gate pattern)
- Conversation state is process-local (no distributed state across multiple instances)
- Background queue is bounded to 256 items (older events may be dropped if queue fills)

### Dependencies
- LINE Messaging API SDK
- Google Gemini API
- OpenAI GPT API
- Anthropic Claude API
- DocumentFormat.OpenXml
- xUnit for testing

### Migration Notes
- First production release; no migration path from previous versions
- Ensure environment variables are configured for all AI providers
- Set `App:AllowGroupFileHandling` if group file support is needed
- Configure GitHub Actions secrets for Render deployment

---

## Format Notes

- **[Unreleased]** - Work not yet released (always at the top)
- **[X.Y.Z]** - Released versions with dates in YYYY-MM-DD format
- Categories: Added, Changed, Deprecated, Removed, Fixed, Security
- Links to comparisons should be updated in the footer

## Release Process

To create a new release:

1. Move [Unreleased] changes into new version section with today's date
2. Create git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
3. Push tag: `git push origin vX.Y.Z`
4. Create GitHub Release with automated notes from CHANGELOG.md
5. Update any relevant documentation

---

**Repository**: [arcobaleno64/LINE-BOT](https://github.com/arcobaleno64/LINE-BOT)  
**First Release**: 2026-04-16  
**Maintainer**: @arcobaleno64
