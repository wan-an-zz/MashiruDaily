using Foundation;
using UIKit;
using Avalonia;
using Avalonia.Controls;
using Avalonia.iOS;
using Avalonia.Media;

namespace MashiruDaily.iOS;

// 应用的 UIApplicationDelegate。该类负责启动应用的用户界面，
// 并监听（可选地响应）来自 iOS 的应用事件。
[Register("AppDelegate")]
#pragma warning disable CA1711 // 标识符不应使用不正确的后缀
public partial class AppDelegate : AvaloniaAppDelegate<App>
#pragma warning restore CA1711 // 标识符不应使用不正确的后缀
{
    protected override AppBuilder CustomizeAppBuilder(AppBuilder builder)
    {
        return base.CustomizeAppBuilder(builder)
            .WithInterFont();
    }
}
