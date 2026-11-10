"""Remote access (2026-11-10): Setup-Remote.bat / remote_setup.py and nm_control.py - the parts that do not need Windows."""
import json
import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent  # noqa: E402
import nm_control  # noqa: E402
import remote_setup as RS  # noqa: E402

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
DEFAULT_SSHD = """# This is the sshd server system-wide configuration file.
#Port 22
#AddressFamily any
#ListenAddress 0.0.0.0
#ListenAddress ::
ListenAddress 0.0.0.0
#PasswordAuthentication yes
Subsystem\tsftp\tsftp-server.exe

Match Group administrators
       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
"""
REPLY = {"host": "87.107.160.17", "ssh_port": 22, "user": "nmtunnel", "listen_port": 22201, "local_port": 22,
         "known_hosts": "87.107.160.17 ssh-ed25519 AAAAHOST", "admin_pubkey": "ssh-ed25519 AAAAADMIN root@vps"}


class SshdConfigTests(unittest.TestCase):
    def test_our_block_comes_first_and_nothing_else_listens(self):
        out = RS.configured_sshd_text(DEFAULT_SSHD)
        lines = out.splitlines()
        self.assertEqual(lines[0], RS.BLOCK_BEGIN)
        self.assertEqual(lines[1:5], ["ListenAddress 127.0.0.1", "PasswordAuthentication no", "PubkeyAuthentication yes",
                                      "PermitEmptyPasswords no"])
        active = [ln for ln in lines if ln.strip().lower().startswith("listenaddress")]
        self.assertEqual(active, ["ListenAddress 127.0.0.1"])
        self.assertIn("#NM# ListenAddress 0.0.0.0", lines)
        self.assertIn("Match Group administrators", out)
        self.assertLess(out.index(RS.BLOCK_END), out.index("Match Group"))   # before any Match block

    def test_running_it_again_changes_nothing(self):
        once = RS.configured_sshd_text(DEFAULT_SSHD)
        self.assertEqual(RS.configured_sshd_text(once), once)


class KeysAndScriptsTests(unittest.TestCase):
    def test_the_admin_key_replaces_only_its_own_line(self):
        text = "ssh-ed25519 AAAAOWN me@laptop\nssh-ed25519 AAAAOLD nm-vps-admin\n"
        out = RS.merge_admin_key(text, REPLY["admin_pubkey"])
        self.assertEqual(out, "ssh-ed25519 AAAAOWN me@laptop\nssh-ed25519 AAAAADMIN nm-vps-admin\n")
        self.assertEqual(RS.merge_admin_key("", REPLY["admin_pubkey"]), "ssh-ed25519 AAAAADMIN nm-vps-admin\n")

    def test_the_tunnel_loop(self):
        cmd = RS.tunnel_cmd(r"C:\Windows\System32\OpenSSH\ssh.exe", REPLY)
        self.assertIn("-R 127.0.0.1:22201:127.0.0.1:22 nmtunnel@87.107.160.17", cmd)
        self.assertIn("StrictHostKeyChecking=yes", cmd)
        self.assertIn("ExitOnForwardFailure=yes", cmd)
        self.assertIn('-i "%D%tunnel_key"', cmd)
        self.assertIn("ping -n 16 127.0.0.1", cmd)          # timeout.exe needs a console; the SYSTEM task has none
        self.assertNotIn("timeout /t", cmd)
        self.assertIn('if exist "%D%tunnel.log" for', cmd)
        self.assertIn("\r\n", cmd)                           # cmd.exe wants CRLF

    def test_the_control_launcher_follows_the_running_copy(self):
        cmd = RS.control_cmd()
        self.assertIn('set /p NMHOME=<"%D%home.txt"', cmd)
        self.assertIn('"%NMPY%" "%NMHOME%\\nm_control.py" %*', cmd)


class TaskXmlTests(unittest.TestCase):
    def test_the_tunnel_task_runs_as_system_at_boot_and_comes_back(self):
        root = ET.fromstring(RS.tunnel_task_xml().split("\n", 1)[1])
        self.assertEqual(root.find("t:Principals/t:Principal/t:UserId", NS).text, "S-1-5-18")
        self.assertIsNotNone(root.find("t:Triggers/t:BootTrigger", NS))
        self.assertEqual(root.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", NS).text, "PT5M")
        self.assertEqual(root.find("t:Settings/t:MultipleInstancesPolicy", NS).text, "IgnoreNew")
        self.assertEqual(root.find("t:Settings/t:ExecutionTimeLimit", NS).text, "PT0S")
        self.assertIn("tunnel.cmd", root.find("t:Actions/t:Exec/t:Arguments", NS).text)

    def test_the_node_task_is_interactive_and_on_demand(self):
        root = ET.fromstring(RS.node_task_xml(r"DESKTOP-X\QQz", r"C:\N\Main V4\processing-server").split("\n", 1)[1])
        p = root.find("t:Principals/t:Principal", NS)
        self.assertEqual(p.find("t:UserId", NS).text, r"DESKTOP-X\QQz")
        self.assertEqual(p.find("t:LogonType", NS).text, "InteractiveToken")
        self.assertEqual(list(root.find("t:Triggers", NS)), [])      # never by itself: only the site's «start»
        ex = root.find("t:Actions/t:Exec", NS)
        self.assertEqual(ex.find("t:Arguments", NS).text, r'/d /c "C:\N\Main V4\processing-server\START.bat"')
        self.assertEqual(ex.find("t:WorkingDirectory", NS).text, r"C:\N\Main V4\processing-server")

    def test_xml_special_characters_are_escaped(self):
        xml = RS.node_task_xml("PC\\A&B", r"C:\a<b>")
        ET.fromstring(xml.split("\n", 1)[1])

    def test_not_on_linux(self):
        self.assertEqual(RS.main([]), 1)


class ControlTests(unittest.TestCase):
    ROWS = [
        {"ProcessId": 10, "ParentProcessId": 1, "Name": "cmd.exe",
         "CommandLine": 'C:\\Windows\\system32\\cmd.exe /c ""C:\\N\\Main V4\\processing-server\\START.bat" "'},
        {"ProcessId": 11, "ParentProcessId": 10, "Name": "python.exe",
         "CommandLine": 'python  "C:\\N\\Main V4\\processing-server\\agent.py"'},
        {"ProcessId": 12, "ParentProcessId": 10, "Name": "python.exe",
         "CommandLine": 'python  "C:\\N\\Main V4\\processing-server\\agent.py" --version'},
        {"ProcessId": 13, "ParentProcessId": 1, "Name": "python.exe", "CommandLine": "python other.py"},
        {"ProcessId": 14, "ParentProcessId": 1, "Name": "ollama.exe", "CommandLine": "ollama serve"},
    ]

    def test_it_finds_the_start_window_and_the_agent_only(self):
        rows = nm_control.parse_processes(json.dumps(self.ROWS))
        starts, agents = nm_control.node_processes(rows)
        self.assertEqual([r["pid"] for r in starts], [10])
        self.assertEqual([r["pid"] for r in agents], [11])
        self.assertEqual(nm_control.node_folder(self.ROWS[1]["CommandLine"], "agent.py"), r"C:\N\Main V4\processing-server")

    def test_one_process_is_a_dict_not_a_list(self):
        self.assertEqual(len(nm_control.parse_processes(json.dumps(self.ROWS[0]))), 1)
        self.assertEqual(nm_control.parse_processes("not json"), [])

    def test_logs_read_old_utf16_files(self):
        self.assertEqual(nm_control.decode_log("line one\r\n".encode("utf-16")), "line one\r\n")
        self.assertEqual(nm_control.decode_log("x".encode()), "x")

    def test_unknown_command(self):
        self.assertEqual(nm_control.main(["format"]), 2)


class AgentTests(unittest.TestCase):
    def test_the_agent_keeps_home_txt_current(self):
        self.assertEqual(agent.VERSION, "2.9")
        agent.note_home()                         # not on Windows: does nothing, never raises


if __name__ == "__main__":
    unittest.main()
