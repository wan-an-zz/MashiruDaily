using UIKit;

namespace MashiruDaily.iOS;

public class Application
{
    // 这是应用的主入口。
    static void Main(string[] args)
    {
        // 如果你想使用与 "AppDelegate" 不同的 Application Delegate 类，
        // 可以在这里指定。
        UIApplication.Main(args, null, typeof(AppDelegate));
    }
}
