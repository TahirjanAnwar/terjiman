// Terjiman.exe: starts Terjiman with its own Python (.venv) and passes on its arguments (such as --tray).
// setup.cmd builds it with the C# compiler that comes with Windows (.NET Framework 4), so there is a real
// program with a name and an icon for the desktop, the Start menu and "start with Windows".
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Terjiman")]
[assembly: AssemblyDescription("Terjiman: write in Uyghur, send in English")]
[assembly: AssemblyProduct("Terjiman")]
[assembly: AssemblyCompany("T-production")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

static class Launcher
{
    [STAThread]
    static int Main(string[] args)
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(dir, @".venv\Scripts\pythonw.exe");
        string script = Path.Combine(dir, "terjiman.py");
        if (!File.Exists(python) || !File.Exists(script))
        {
            MessageBox.Show("Terjiman isn't set up yet.\n\nRun setup.cmd in:\n" + dir, "Terjiman",
                            MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
        StringBuilder line = new StringBuilder(Quote(script));
        foreach (string arg in args)
            line.Append(' ').Append(Quote(arg));
        ProcessStartInfo start = new ProcessStartInfo(python, line.ToString());
        start.UseShellExecute = false;
        start.WorkingDirectory = dir;
        try
        {
            Process.Start(start);
        }
        catch (Exception error)
        {
            MessageBox.Show("Terjiman couldn't start:\n" + error.Message, "Terjiman",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }

    // Quotes one argument the way Windows programs split their command line.
    static string Quote(string arg)
    {
        if (arg.Length > 0 && arg.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0)
            return arg;
        StringBuilder text = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in arg)
        {
            if (c == '\\') { slashes++; continue; }
            text.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
            text.Append(c);
            slashes = 0;
        }
        text.Append('\\', slashes * 2);
        return text.Append('"').ToString();
    }
}
