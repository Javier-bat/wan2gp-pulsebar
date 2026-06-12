using System;
using System.Drawing;
using System.IO;
using System.Text.Json;
using System.Windows.Forms;

namespace Wan2GP.PulseBar;

public sealed class FloatingBarForm : Form
{
    private readonly string _statusPath;
    private readonly System.Windows.Forms.Timer _timer;
    private readonly NotifyIcon _trayIcon;
    private readonly Label _titleLabel;
    private readonly Label _detailLabel;
    private readonly ProgressBar _progressBar;
    private readonly Button _hideButton;
    private readonly Button _closeButton;
    private string _lastTerminalState = "";

    public FloatingBarForm(string statusPath)
    {
        _statusPath = statusPath;

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

        var screen = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 720);
        Location = new Point(screen.Right - Width - 16, screen.Top + 16);

        _titleLabel = new Label
        {
            AutoSize = false,
            Left = 12,
            Top = 8,
            Width = 290,
            Height = 20,
            Text = "Wan2GP idle",
            ForeColor = Color.White
        };

        _detailLabel = new Label
        {
            AutoSize = false,
            Left = 310,
            Top = 8,
            Width = 70,
            Height = 20,
            Text = "0%",
            TextAlign = ContentAlignment.MiddleRight,
            ForeColor = Color.White
        };

        _hideButton = new Button
        {
            Left = 386,
            Top = 6,
            Width = 30,
            Height = 24,
            Text = "_",
            FlatStyle = FlatStyle.Flat
        };
        _hideButton.FlatAppearance.BorderColor = Color.FromArgb(85, 90, 100);
        _hideButton.Click += (_, _) => HideToTray();

        _closeButton = new Button
        {
            Left = 420,
            Top = 6,
            Width = 30,
            Height = 24,
            Text = "x",
            FlatStyle = FlatStyle.Flat
        };
        _closeButton.FlatAppearance.BorderColor = Color.FromArgb(85, 90, 100);
        _closeButton.Click += (_, _) => Close();

        _progressBar = new ProgressBar
        {
            Left = 12,
            Top = 38,
            Width = 438,
            Height = 16,
            Minimum = 0,
            Maximum = 100,
            Value = 0,
            Style = ProgressBarStyle.Continuous
        };

        Controls.Add(_titleLabel);
        Controls.Add(_detailLabel);
        Controls.Add(_hideButton);
        Controls.Add(_closeButton);
        Controls.Add(_progressBar);

        _trayIcon = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = "Wan2GP Pulsebar",
            Visible = true,
            ContextMenuStrip = BuildTrayMenu()
        };
        _trayIcon.DoubleClick += (_, _) => ShowFromTray();

        _timer = new System.Windows.Forms.Timer
        {
            Interval = 1000
        };
        _timer.Tick += (_, _) => RefreshStatus();
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
        var menu = new ContextMenuStrip();
        menu.Items.Add("Show", null, (_, _) => ShowFromTray());
        menu.Items.Add("Hide", null, (_, _) => HideToTray());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Exit", null, (_, _) => Close());
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
                SetStatus("waiting", 0, "Waiting for status.json");
                return;
            }

            using var stream = File.Open(_statusPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using var doc = JsonDocument.Parse(stream);
            var root = doc.RootElement;

            var state = GetString(root, "state", "idle");
            var percent = GetInt(root, "percent", 0);
            var stage = GetString(root, "stage", state);
            var message = GetString(root, "message", stage);
            var queueText = BuildQueueText(root);
            var detail = string.IsNullOrWhiteSpace(queueText)
                ? $"{percent}%"
                : $"{percent}% {queueText}";

            SetStatus(message, percent, detail);
            _trayIcon.Text = TrimTrayText($"Wan2GP: {percent}% {state}");
            MaybeNotifyTerminalState(state, message);
        }
        catch
        {
            SetStatus("Status file is being updated", 0, "...");
        }
    }

    private void SetStatus(string title, int percent, string detail)
    {
        var safePercent = Math.Max(0, Math.Min(100, percent));
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

        var key = $"{state}:{message}";
        if (_lastTerminalState == key)
        {
            return;
        }

        _lastTerminalState = key;
        _trayIcon.BalloonTipTitle = state == "done" ? "Wan2GP completed" : "Wan2GP failed";
        _trayIcon.BalloonTipText = TrimTrayText(message);
        _trayIcon.ShowBalloonTip(4000);
    }

    private static string BuildQueueText(JsonElement root)
    {
        if (!root.TryGetProperty("queue", out var queue) || queue.ValueKind != JsonValueKind.Object)
        {
            return "";
        }

        var current = GetNullableInt(queue, "current");
        var total = GetNullableInt(queue, "total");
        if (current is null || total is null || total <= 0)
        {
            return "";
        }

        return $"({current}/{total})";
    }

    private static string GetString(JsonElement root, string property, string fallback)
    {
        if (root.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String)
        {
            return value.GetString() ?? fallback;
        }

        return fallback;
    }

    private static int GetInt(JsonElement root, string property, int fallback)
    {
        if (root.TryGetProperty(property, out var value) && value.TryGetInt32(out var result))
        {
            return result;
        }

        return fallback;
    }

    private static int? GetNullableInt(JsonElement root, string property)
    {
        if (root.TryGetProperty(property, out var value) && value.TryGetInt32(out var result))
        {
            return result;
        }

        return null;
    }

    private static string TrimLabel(string value, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return "";
        }

        return value.Length <= maxLength ? value : value[..Math.Max(0, maxLength - 1)] + "...";
    }

    private static string TrimTrayText(string value)
    {
        return TrimLabel(value, 60);
    }
}
