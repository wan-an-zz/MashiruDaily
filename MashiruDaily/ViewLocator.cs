using System;
using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using MashiruDaily.Core.ViewModels;

namespace MashiruDaily;

/// <summary>
/// 给定视图模型，尽可能返回对应的视图。
/// </summary>
[RequiresUnreferencedCode(
    "Default implementation of ViewLocator involves reflection which may be trimmed away.",
    Url = "https://docs.avaloniaui.net/docs/concepts/view-locator")]
public class ViewLocator : IDataTemplate
{
    public Control? Build(object? param)
    {
        if (param is null)
            return null;

        var fullName = param.GetType().FullName!;
        var name = fullName
            .Replace("MashiruDaily.Core.ViewModels", "MashiruDaily.Views", StringComparison.Ordinal)
            .Replace("ViewModel", "View", StringComparison.Ordinal);
        var type = Type.GetType(name);

        if (type != null)
        {
            return (Control)Activator.CreateInstance(type)!;
        }

        return new TextBlock { Text = "未找到视图：" + name };
    }

    public bool Match(object? data)
    {
        return data is ViewModelBase;
    }
}