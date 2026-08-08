using MashiruDaily.ViewModels.Todo;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

internal sealed class MainWindow : Runnable
{
    public MainWindow(TodoPageViewModel viewModel)
    {
        Title = "MashiruDaily - Todo";
    }
}
