using Android.App;
using Android.Runtime;
using Avalonia;
using Avalonia.Android;
using MashiruDaily.Assets;

namespace MashiruDaily.Android
{
    [Application]
    public class Application : AvaloniaAndroidApplication<App>
    {
        protected Application(nint javaReference, JniHandleOwnership transfer) : base(javaReference, transfer)
        {
        }

        protected override AppBuilder CustomizeAppBuilder(AppBuilder builder)
        {
            return base.CustomizeAppBuilder(builder)
                // 选项必须在 ConfigureFonts 创建 FontManager 之前绑定。
                .With(AppFonts.CreateFontManagerOptions())
                .ConfigureFonts(fontManager => fontManager.AddFontCollection(new NotoSansSCFontCollection()))
                .WithInterFont();
        }
    }
}
