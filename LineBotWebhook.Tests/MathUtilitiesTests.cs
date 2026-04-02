using LineBotWebhook.Services.Documents;
using Xunit;

namespace LineBotWebhook.Tests;

public class MathUtilitiesTests
{
    [Fact]
    public void CosineSimilarity_IdenticalVectors_ReturnsOne()
    {
        float[] a = [1.0f, 2.0f, 3.0f];
        float[] b = [1.0f, 2.0f, 3.0f];

        var result = MathUtilities.CosineSimilarity(a, b);

        Assert.InRange(result, 0.999f, 1.001f);
    }

    [Fact]
    public void CosineSimilarity_OrthogonalVectors_ReturnsZero()
    {
        float[] a = [1.0f, 0.0f];
        float[] b = [0.0f, 1.0f];

        var result = MathUtilities.CosineSimilarity(a, b);

        Assert.Equal(0.0f, result);
    }

    [Fact]
    public void CosineSimilarity_OppositeVectors_ReturnsMinusOne()
    {
        float[] a = [1.0f, 2.0f];
        float[] b = [-1.0f, -2.0f];

        var result = MathUtilities.CosineSimilarity(a, b);

        Assert.InRange(result, -1.001f, -0.999f);
    }

    [Fact]
    public void CosineSimilarity_DifferentLengths_ThrowsArgumentException()
    {
        float[] a = [1.0f, 2.0f];
        float[] b = [1.0f, 2.0f, 3.0f];

        Assert.Throws<ArgumentException>(() => MathUtilities.CosineSimilarity(a, b));
    }
}
