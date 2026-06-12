using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace Wan2GP.PulseBar.Legacy
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            string statusPath = args.Length > 0
                ? args[0]
                : Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", "status.json"));

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new FloatingBarForm(statusPath));
        }
    }

    public sealed class FloatingBarForm : Form
    {
        private readonly string _statusPath;
        private readonly Timer _timer;
        private readonly NotifyIcon _trayIcon;
        private readonly Label _titleLabel;
        private readonly Label _detailLabel;
        private readonly ProgressBar _progressBar;
        private readonly Button _hideButton;
        private readonly Button _closeButton;
        private readonly JavaScriptSerializer _json;
        private string _lastTerminalState = "";

        public FloatingBarForm(string statusPath)
        {
            _statusPath = statusPath;
            _json = new JavaScriptSerializer();

            Text = "Wan2GP Pulsebar";
            Width = 460;
            Height = 78;
            MinimumSize = new Size(360, 78);
            MaximumSize = new Size(900, 78);
            FormBorderStyle = FormBorderStyle.FixedToolWindow;
            StartPosition = FormStartPosition.Manual;
            TopMost = true;
            ShowInTaskbar = true;
            BackColor = Color.FromArgb(30, 32, 36);
            ForeColor = Color.White;
            Font = new Font("Segoe UI", 9F, FontStyle.Regular, GraphicsUnit.Point);

            Rectangle screen = Screen.PrimaryScreen != null
                ? Screen.PrimaryScreen.WorkingArea
                : new Rectangle(0, 0, 1280, 720);
            Location = new Point(screen.Right - Width - 16, screen.Top + 16);

            _titleLabel = new Label();
            _titleLabel.AutoSize = false;
            _titleLabel.Left = 12;
            _titleLabel.Top = 8;
            _titleLabel.Width = 290;
            _titleLabel.Height = 20;
            _titleLabel.Text = "Wan2GP idle";
            _titleLabel.ForeColor = Color.White;

            _detailLabel = new Label();
            _detailLabel.AutoSize = false;
            _detailLabel.Left = 310;
            _detailLabel.Top = 8;
            _detailLabel.Width = 70;
            _detailLabel.Height = 20;
            _detailLabel.Text = "0%";
            _detailLabel.TextAlign = ContentAlignment.MiddleRight;
            _detailLabel.ForeColor = Color.White;

            _hideButton = new Button();
            _hideButton.Left = 386;
            _hideButton.Top = 6;
            _hideButton.Width = 30;
            _hideButton.Height = 24;
            _hideButton.Text = "_";
            _hideButton.FlatStyle = FlatStyle.Flat;
            _hideButton.FlatAppearance.BorderColor = Color.FromArgb(85, 90, 100);
            _hideButton.Click += delegate { HideToTray(); };

            _closeButton = new Button();
            _closeButton.Left = 420;
            _closeButton.Top = 6;
            _closeButton.Width = 30;
            _closeButton.Height = 24;
            _closeButton.Text = "x";
            _closeButton.FlatStyle = FlatStyle.Flat;
            _closeButton.FlatAppearance.BorderColor = Color.FromArgb(85, 90, 100);
            _closeButton.Click += delegate { Close(); };

            _progressBar = new ProgressBar();
            _progressBar.Left = 12;
            _progressBar.Top = 38;
            _progressBar.Width = 438;
            _progressBar.Height = 16;
            _progressBar.Minimum = 0;
            _progressBar.Maximum = 100;
            _progressBar.Value = 0;
            _progressBar.Style = ProgressBarStyle.Continuous;

            Controls.Add(_titleLabel);
            Controls.Add(_detailLabel);
            Controls.Add(_hideButton);
            Controls.Add(_closeButton);
            Controls.Add(_progressBar);

            _trayIcon = new NotifyIcon();
            _trayIcon.Icon = SystemIcons.Application;
            _trayIcon.Text = "Wan2GP Pulsebar";
            _trayIcon.Visible = true;
            _trayIcon.ContextMenuStrip = BuildTrayMenu();
            _trayIcon.DoubleClick += delegate { ShowFromTray(); };

            _timer = new Timer();
            _timer.Interval = 1000;
            _timer.Tick += delegate { RefreshStatus(); };
            _timer.Start();

            RefreshStatus();
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            _timer.Stop();
            _trayIcon.Visible = false;
            _trayIcon.Dispose();
            base.OnFormClosing(e);
        }

        private ContextMenuStrip BuildTrayMenu()
        {
            ContextMenuStrip menu = new ContextMenuStrip();
            menu.Items.Add("Show", null, delegate { ShowFromTray(); });
            menu.Items.Add("Hide", null, delegate { HideToTray(); });
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Exit", null, delegate { Close(); });
            return menu;
        }

        private void HideToTray()
        {
            ShowInTaskbar = false;
            Hide();
        }

        private void ShowFromTray()
        {
            ShowInTaskbar = true;
            Show();
            WindowState = FormWindowState.Normal;
            Activate();
        }

        private void RefreshStatus()
        {
            try
            {
                if (!File.Exists(_statusPath))
                {
                    SetStatus("Waiting for status.json", 0, "waiting");
                    return;
                }

                string jsonText;
                using (FileStream stream = File.Open(_statusPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (StreamReader reader = new StreamReader(stream))
                {
                    jsonText = reader.ReadToEnd();
                }

                Dictionary<string, object> root = _json.Deserialize<Dictionary<string, object>>(jsonText);
                string state = GetString(root, "state", "idle");
                int percent = GetInt(root, "percent", 0);
                string stage = GetString(root, "stage", state);
                string message = GetString(root, "message", stage);
                string queueText = BuildQueueText(root);
                string detail = string.IsNullOrWhiteSpace(queueText)
                    ? string.Format("{0}%", percent)
                    : string.Format("{0}% {1}", percent, queueText);

                SetStatus(message, percent, detail);
                _trayIcon.Text = TrimTrayText(string.Format("Wan2GP: {0}% {1}", percent, state));
                MaybeNotifyTerminalState(state, message);
            }
            catch
            {
                SetStatus("Status file is being updated", 0, "...");
            }
        }

        private void SetStatus(string title, int percent, string detail)
        {
            int safePercent = Math.Max(0, Math.Min(100, percent));
            _titleLabel.Text = TrimLabel(title, 56);
            _detailLabel.Text = TrimLabel(detail, 16);
            _progressBar.Value = safePercent;
        }

        private void MaybeNotifyTerminalState(string state, string message)
        {
            if (state != "done" && state != "failed" && state != "error")
            {
                _lastTerminalState = "";
                return;
            }

            string key = string.Format("{0}:{1}", state, message);
            if (_lastTerminalState == key)
            {
                return;
            }

            _lastTerminalState = key;
            _trayIcon.BalloonTipTitle = state == "done" ? "Wan2GP completed" : "Wan2GP failed";
            _trayIcon.BalloonTipText = TrimTrayText(message);
            _trayIcon.ShowBalloonTip(4000);
        }

        private static string BuildQueueText(Dictionary<string, object> root)
        {
            if (!root.ContainsKey("queue"))
            {
                return "";
            }

            Dictionary<string, object> queue = root["queue"] as Dictionary<string, object>;
            if (queue == null)
            {
                return "";
            }

            int? current = GetNullableInt(queue, "current");
            int? total = GetNullableInt(queue, "total");
            if (!current.HasValue || !total.HasValue || total.Value <= 0)
            {
                return "";
            }

            return string.Format("({0}/{1})", current.Value, total.Value);
        }

        private static string GetString(Dictionary<string, object> root, string property, string fallback)
        {
            if (root.ContainsKey(property) && root[property] != null)
            {
                return Convert.ToString(root[property]);
            }

            return fallback;
        }

        private static int GetInt(Dictionary<string, object> root, string property, int fallback)
        {
            int? value = GetNullableInt(root, property);
            return value.HasValue ? value.Value : fallback;
        }

        private static int? GetNullableInt(Dictionary<string, object> root, string property)
        {
            if (!root.ContainsKey(property) || root[property] == null)
            {
                return null;
            }

            try
            {
                return Convert.ToInt32(root[property]);
            }
            catch
            {
                return null;
            }
        }

        private static string TrimLabel(string value, int maxLength)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "";
            }

            return value.Length <= maxLength ? value : value.Substring(0, Math.Max(0, maxLength - 1)) + "...";
        }

        private static string TrimTrayText(string value)
        {
            return TrimLabel(value, 60);
        }
    }
}

