using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Program {
    [STAThread]
    static void Main(string[] args) {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        
        // Search candidates for the unpacked high-performance distribution
        string[] candidates = new string[] {
            Path.Combine(baseDir, "APFS Explorer", "APFS_Explorer.exe"),
            Path.Combine(baseDir, "dist", "APFS_Explorer", "APFS_Explorer.exe"),
            @"C:\Users\d13\Desktop\APFS Explorer\APFS_Explorer.exe",
            @"C:\Users\d13\Desktop\Projects\APFS Explore in Windows\dist\APFS_Explorer\APFS_Explorer.exe"
        };

        string targetExe = null;
        foreach (string candidate in candidates) {
            if (File.Exists(candidate)) {
                targetExe = candidate;
                break;
            }
        }

        if (targetExe != null) {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = targetExe;
            psi.WorkingDirectory = Path.GetDirectoryName(targetExe);
            psi.UseShellExecute = true;
            psi.Verb = "runas";
            try {
                Process.Start(psi);
            } catch (Exception ex) {
                // User may have cancelled UAC or error occurred
            }
        } else {
            MessageBox.Show(
                "Could not find the APFS Explorer application bundle.\n\nChecked locations:\n" + string.Join("\n", candidates),
                "APFS Explorer",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
    }
}
