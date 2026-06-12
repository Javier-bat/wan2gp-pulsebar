using System;
using System.Windows.Forms;

namespace Wan2GP.PulseBar;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        var statusPath = args.Length > 0
            ? args[0]
            : Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "status.json");

        ApplicationConfiguration.Initialize();
        Application.Run(new FloatingBarForm(Path.GetFullPath(statusPath)));
    }
}

