using System.Text.Encodings.Web;
using System.Text.Json;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class AdvisoryFlowTests
{
    [Fact]
    public void Parser_StructuredTags_ExtractsAllThreeSections()
    {
        var input = """
<conclusion>新建專案優先 OIDC，既有對外整合維持 SAML 即可。</conclusion>
<recommendations>
• 列出兩個整合對象之既有支援能力
• 評估 token 生命週期需求
• 建立 PoC：取一個非關鍵系統做兩週測試
</recommendations>
<questions>
• 既有系統的 SP 端有哪些已在 production？
• 換 OIDC 之動機，是因為實作便利還是安全模型考量？
</questions>
""";

        var result = AdvisoryResponseParser.Parse(input);

        Assert.True(result.IsStructured);
        Assert.Contains("OIDC", result.Conclusion, StringComparison.Ordinal);
        Assert.Equal(3, result.Recommendations.Count);
        Assert.Equal(2, result.Questions.Count);
        Assert.Contains(result.Recommendations, r => r.Contains("PoC", StringComparison.Ordinal));
        Assert.Contains(result.Questions, q => q.Contains("OIDC", StringComparison.Ordinal));
    }

    [Fact]
    public void Parser_NoTags_ReturnsPlain()
    {
        var result = AdvisoryResponseParser.Parse("好的，謝謝");

        Assert.False(result.IsStructured);
        Assert.Equal("好的，謝謝", result.PlainFallback);
        Assert.Empty(result.Recommendations);
        Assert.Empty(result.Questions);
    }

    [Fact]
    public void Parser_PartialTags_StillExtractsWhatExists()
    {
        var input = "<conclusion>請補件再議。</conclusion>正文";

        var result = AdvisoryResponseParser.Parse(input);

        Assert.True(result.IsStructured);
        Assert.Equal("請補件再議。", result.Conclusion);
        Assert.Empty(result.Recommendations);
        Assert.Empty(result.Questions);
    }

    [Fact]
    public void Parser_NumberedBullets_StripsPrefix()
    {
        var input = """
<recommendations>
1. 先補資料
2) 再做驗證
- 然後審核
</recommendations>
""";

        var result = AdvisoryResponseParser.Parse(input);

        Assert.Equal(3, result.Recommendations.Count);
        Assert.Equal("先補資料", result.Recommendations[0]);
        Assert.Equal("再做驗證", result.Recommendations[1]);
        Assert.Equal("然後審核", result.Recommendations[2]);
    }

    [Fact]
    public void ContextStore_Save_ReturnsRetrievableToken()
    {
        var store = new AdvisoryContextStore();
        var ctx = new AdvisoryContext("user-1", "原始問題", "結論");

        var token = store.Save(ctx);
        var retrieved = store.Get(token);

        Assert.NotNull(retrieved);
        Assert.Equal("user-1", retrieved!.UserKey);
        Assert.Equal("原始問題", retrieved.OriginalPrompt);
    }

    [Fact]
    public void ContextStore_UnknownToken_ReturnsNull()
    {
        var store = new AdvisoryContextStore();
        Assert.Null(store.Get("nonexistent"));
        Assert.Null(store.Get(string.Empty));
        Assert.Null(store.Get(null));
    }

    [Fact]
    public void FlexBuilder_AdvisoryBubble_IncludesAllSectionsAndButtons()
    {
        var advisory = new AdvisoryResponse(
            IsStructured: true,
            Conclusion: "新案優先 OIDC。",
            Recommendations: ["先做 PoC", "評估生命週期"],
            Questions: ["既有 SP 是否支援？"],
            PlainFallback: "fallback");

        var bubble = FlexMessageBuilder.BuildAdvisoryBubble(advisory, contextToken: "abc123", offerSearch: true);
        var json = JsonSerializer.Serialize(bubble, new JsonSerializerOptions
        {
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping
        });

        Assert.Contains("教授建議", json, StringComparison.Ordinal);
        Assert.Contains("OIDC", json, StringComparison.Ordinal);
        Assert.Contains("先做 PoC", json, StringComparison.Ordinal);
        Assert.Contains("既有 SP", json, StringComparison.Ordinal);
        Assert.Contains("action=example&token=abc123", json, StringComparison.Ordinal);
        Assert.Contains("action=improve&token=abc123", json, StringComparison.Ordinal);
        Assert.Contains("action=research&token=abc123", json, StringComparison.Ordinal);
    }

    [Fact]
    public void FlexBuilder_AdvisoryBubble_OfferSearchFalse_OmitsResearchButton()
    {
        var advisory = new AdvisoryResponse(
            IsStructured: true,
            Conclusion: "簡短結論",
            Recommendations: ["建議一"],
            Questions: [],
            PlainFallback: "x");

        var bubble = FlexMessageBuilder.BuildAdvisoryBubble(advisory, contextToken: "tok", offerSearch: false);
        var json = JsonSerializer.Serialize(bubble, new JsonSerializerOptions
        {
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping
        });

        Assert.DoesNotContain("action=research", json, StringComparison.Ordinal);
        Assert.Contains("action=example", json, StringComparison.Ordinal);
    }

    [Fact]
    public void SystemPrompt_GroupContext_IncludesGroupConstraint()
    {
        var basePrompt = "你是教授";
        var prompt = LineReplyTextFormatter.BuildSystemPrompt(basePrompt, enableQuickReplies: true, isGroupContext: true);

        Assert.Contains("群組", prompt, StringComparison.Ordinal);
        Assert.Contains("conclusion", prompt, StringComparison.Ordinal);
        Assert.Contains("quick-replies", prompt, StringComparison.Ordinal);
    }

    [Fact]
    public void Sanitizer_StrayAdvisoryTags_AreStrippedFromPlainText()
    {
        var input = "<conclusion>結論</conclusion>本文內容";
        var sanitized = LineReplyTextFormatter.SanitizeForLine(input);

        Assert.DoesNotContain("<conclusion>", sanitized, StringComparison.Ordinal);
        Assert.DoesNotContain("</conclusion>", sanitized, StringComparison.Ordinal);
        Assert.Contains("結論", sanitized, StringComparison.Ordinal);
        Assert.Contains("本文內容", sanitized, StringComparison.Ordinal);
    }
}
