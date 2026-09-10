/**
 * Git Smart Manager — Full GitHub-like UI
 */
const { createApp, ref, computed, onMounted, watch } = Vue;

const app = createApp({
    compilerOptions: { delimiters: ['[[', ']]'] },

    setup() {
        // ── Navigation ──
        const navTab = ref('home');
        function goHome() { navTab.value = 'home'; selectedProject.value = null; }

        // ── State ──
        const projects = ref([]);
        const filteredProjects = ref([]);
        const selectedProject = ref(null);
        const searchQuery = ref('');
        const selectedBranch = ref('');

        // Resizable panel widths
        const sidebarWidth = ref(200);
        const treeWidth = ref(280);
        const isResizingSidebar = ref(false);
        const isResizingTree = ref(false);

        // Project data
        const projectStatus = ref({ branch: '?', files: [], ahead: 0, behind: 0, has_conflict: false });
        const recentCommits = ref([]);
        const commitLog = ref([]);
        const branches = ref([]);
        const remotes = ref([]);
        const syncResult = ref(null);
        const syncing = ref(null);

        // File tree
        const fileTree = ref([]);
        const fileTreeLoading = ref(false);
        const viewingFile = ref('');
        const fileContent = ref('');
        const fileContentLoading = ref(false);

        // Reset / Restore
        const showResetPanel = ref(false);
        const resetTarget = ref('');
        const showResetConfirm = ref(false);
        const resetResult = ref(null);

        // Git graph
        const graphData = ref([]);
        const graphRowHeight = 32;
        const graphSvgWidth = 120;
        const selectedCommit = ref(null);

        // Graph colors for branch lines
        const graphColors = ['#7c5cfc', '#60a5fa', '#4ade80', '#fb923c', '#f87171', '#22d3ee', '#facc15', '#c084fc', '#34d399', '#f472b6'];

        function parseRefs(refsStr) {
            if (!refsStr) return [];
            const results = [];
            let str = refsStr.replace(/^[\(\)\s,]+|[\(\)\s,]+$/g, '').trim();
            if (!str) return [];
            const parts = str.split(',').map(s => s.trim()).filter(Boolean);
            for (const p of parts) {
                if (p.startsWith('tag:')) {
                    results.push({ type: 'tag', name: p.replace(/^tag:\s*/, '').trim() });
                } else if (p.startsWith('HEAD')) {
                    const rest = p.replace(/^HEAD(?:\s*->\s*)?/, '').trim();
                    if (rest) results.push({ type: 'head', name: rest });
                    else results.push({ type: 'head', name: 'HEAD' });
                } else {
                    results.push({ type: 'branch', name: p });
                }
            }
            return results;
        }

        function authorColor(name) {
            if (!name) return '#666';
            const colors = ['#7c5cfc', '#60a5fa', '#4ade80', '#fb923c', '#f87171', '#22d3ee', '#facc15', '#c084fc', '#34d399', '#f472b6', '#a78bfa'];
            let hash = 0;
            for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
            return colors[Math.abs(hash) % colors.length];
        }

        function authorInitial(name) {
            if (!name) return '?';
            return name.charAt(0).toUpperCase();
        }

        function renderGraphSegments(graphStr, rowIdx) {
            const segments = [];
            if (!graphStr) return segments;
            const chars = graphStr.split('');
            let col = 0;
            for (let i = 0; i < chars.length; i++) {
                const ch = chars[i];
                const x = i * 14 + 8;
                if (ch === '*') {
                    const color = graphColors[i % graphColors.length];
                    segments.push({ type: 'node', x, color });
                    segments.push({ type: 'vert', x, color });
                } else if (ch === '|') {
                    segments.push({ type: 'vert', x: col * 14 + 8, color: graphColors[col % graphColors.length] });
                } else if (ch === '/') {
                    segments.push({ type: 'slash', x1: (col + 1) * 14 + 8, x2: col * 14 + 8, color: graphColors[col % graphColors.length] });
                    col++;
                } else if (ch === '\\') {
                    segments.push({ type: 'backslash', x1: col * 14 + 8, x2: (col + 1) * 14 + 8, color: graphColors[col % graphColors.length] });
                }
            }
            return segments;
        }

        async function fetchGraph() {
            if (!selectedProject.value || !isGitRepo.value) return;
            try {
                const data = await gitCmd(selectedProject.value.id, 'graph', { limit: 50, all: true });
                graphData.value = Array.isArray(data) ? data : [];
            } catch (e) {
                graphData.value = [];
            }
        }

        // Context menu
        const contextMenu = ref({ visible: false, x: 0, y: 0, file: null });

        // UI panels
        const showCommitPanel = ref(false);
        const showBranchPanel = ref(false);

        // Commit
        const commitMessage = ref('');
        const commitDescription = ref('');
        const commitResult = ref(null);
        const autoPushAfterCommit = ref(false);
        const stagedCount = computed(() => {
            return projectStatus.value.files ? projectStatus.value.files.filter(f =>
                ['Staged', 'Staged+Modified', 'Added'].includes(f.status)
            ).length : 0;
        });

        // Branch
        const newBranchName = ref('');
        const branchResult = ref(null);
        const mergeSourceBranch = ref('');
        const merging = ref(false);

        // Releases
        const showReleasesPanel = ref(false);
        const newReleaseTag = ref('');
        const newReleaseDesc = ref('');
        const releases = ref([]);
        const releaseResult = ref(null);

        // Remote
        const newRemoteName = ref('origin');
        const newRemoteUrl = ref('');
        const creatingRemote = ref(null);
        const remoteMap = computed(() => {
            const map = {};
            for (const r of remotes.value) { if (!map[r.name]) map[r.name] = r.url; }
            return map;
        });

        // Init
        const initGitLoading = ref(false);
        const initResult = ref(null);
        const isGitRepo = computed(() => {
            const s = projectStatus.value; return s && s.branch && s.branch !== '?';
        });
        const gitConnectionClass = computed(() => {
            if (!selectedProject.value) return '';
            const p = projectStatus.value;
            if (!p.branch || p.branch === '?') return 'disconnected';
            if (p.has_conflict) return 'conflict';
            if (p.ahead > 0 || p.behind > 0) return 'sync-needed';
            return 'connected';
        });

        // Diff
        const diffContent = ref('');
        const diffFile = ref('');

        // Modals
        const showAddModal = ref(false);
        const showSettingsModal = ref(false);
        const addTab = ref('clone');
        const cloneForm = ref({ url: '', targetDir: '' });
        const createForm = ref({ name: '', description: '', private: false, github: true, gitea: true, targetDir: '' });
        const cloning = ref(false);
        const creating = ref(false);
        const cloneProgress = ref('');
        const createProgress = ref('');

        const settings = ref({});
        const formSettings = ref({ github_token: '', gitea_token: '', gitea_server_url: '', gitea_username: '', gitea_password: '', fork_path: '' });
        const checking = ref({ github: false, gitea: false, password: false });
        const tokenResults = ref({ github: null, gitea: null, password: null });

        const giteaRepos = ref([]);
        const giteaRepoCount = computed(() => giteaRepos.value.length);
        const giteaLoading = ref(false);
        const giteaError = ref('');
        const giteaImporting = ref(null);
        const giteaImportProgress = ref('');
        const giteaImport = ref({ targetDir: '' });

        // GitHub repos
        const githubRepos = ref([]);
        const githubSearchQuery = ref('');
        const githubLoading = ref(false);
        const githubError = ref('');
        const githubImporting = ref(null);
        const filteredGithubRepos = computed(() => {
            if (!githubSearchQuery.value.trim()) return githubRepos.value;
            const q = githubSearchQuery.value.toLowerCase();
            return githubRepos.value.filter(r => (r.name || '').toLowerCase().includes(q) || (r.description || '').toLowerCase().includes(q));
        });

        // ── Lifecycle ──
        onMounted(async () => {
            await loadProjects();
            await loadSettings();
            fetchDashboardGiteaRepos();

            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                // Ctrl+Enter: Commit
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && showCommitPanel.value) {
                    executeCommit();
                }
                // Escape: close panels
                if (e.key === 'Escape') {
                    showCommitPanel.value = false;
                    showBranchPanel.value = false;
                    contextMenu.value.visible = false;
                }
                // 'r': refresh
                if (e.key === 'r' && !e.ctrlKey && !e.metaKey && !e.target.closest('input,textarea')) {
                    refreshAll();
                }
                // 'p': push
                if (e.key === 'p' && !e.ctrlKey && !e.metaKey && !e.target.closest('input,textarea')) {
                    executePush();
                }
                // 'u': pull
                if (e.key === 'u' && !e.ctrlKey && !e.metaKey && !e.target.closest('input,textarea')) {
                    executePull();
                }
            });

            // ── Auto-refresh ──
            // Refresh selected project status/log/graph every 30s
            setInterval(async () => {
                if (!selectedProject.value) return;
                try {
                    const status = await api(`/api/projects/${selectedProject.value.id}/status`);
                    projectStatus.value = status;
                    updateProjectStatus(selectedProject.value.id, status);
                } catch (_) {}
                try {
                    const log = await gitCmd(selectedProject.value.id, 'log', { limit: 30 });
                    commitLog.value = Array.isArray(log) ? log : [];
                } catch (_) {}
                try {
                    const g = await gitCmd(selectedProject.value.id, 'graph', { limit: 50, all: true });
                    graphData.value = Array.isArray(g) ? g : [];
                } catch (_) {}
                try {
                    const bs = await gitCmd(selectedProject.value.id, 'branch_list');
                    branches.value = Array.isArray(bs) ? bs : [];
                } catch (_) {}
                try {
                    const rs = await gitCmd(selectedProject.value.id, 'remote_list');
                    remotes.value = Array.isArray(rs) ? rs : [];
                } catch (_) {}
                selectedBranch.value = projectStatus.value.branch || '';
            }, 30000);

            // Refresh project list (dashboard status dots) every 60s
            setInterval(async () => {
                await loadProjects();
            }, 60000);
        });

        watch(navTab, (tab) => {
            if (tab === 'home' || tab === 'gitea_browse') fetchDashboardGiteaRepos();
        });

        // ── API ──
        async function api(url, options = {}) {
            const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
            const data = await resp.json();
            if (!resp.ok) {
                const errMsg = data.error
                    || data.stderr?.substring(0, 200)
                    || data.message
                    || `Request failed (${resp.status})`;
                throw new Error(errMsg);
            }
            return data;
        }

        async function gitCmd(projectId, cmd, args = {}) {
            return await api(`/api/projects/${projectId}/git/${cmd}`, { method: 'POST', body: JSON.stringify(args) });
        }

        // ── Load / Refresh ──
        async function loadProjects() {
            try { const data = await api('/api/projects'); projects.value = data; filterProjects(); }
            catch (e) { toast(e.message, 'error'); }
        }

        async function loadSettings() {
            try {
                const data = await api('/api/settings');
                settings.value = data;
                formSettings.value.gitea_server_url = data.gitea_server_url || '';
                formSettings.value.fork_path = data.fork_path || '';
                // Show saved indicators for credentials (actual values stay in keyring)
                formSettings.value.github_token = data.has_github_token ? '••••••••' : '';
                formSettings.value.gitea_token = data.has_gitea_token ? '••••••••' : '';
                formSettings.value.gitea_username = data.has_gitea_username ? '••••••••' : '';
                formSettings.value.gitea_password = data.has_gitea_password ? '••••••••' : '';
            } catch (e) {}
        }

        function filterProjects() {
            const q = searchQuery.value.toLowerCase().trim();
            if (!q) { filteredProjects.value = [...projects.value]; return; }
            filteredProjects.value = projects.value.filter(p =>
                p.name.toLowerCase().includes(q) || (p.path && p.path.toLowerCase().includes(q))
            );
        }

        function statusClass(proj) {
            const s = proj.status_summary;
            if (!s || !s.branch || s.branch === '—') return 'unknown';
            if (s.has_conflict) return 'conflict';
            if (s.has_changes) return 'changes';
            return 'clean';
        }

        function statusRowClass(status) { return status === 'Conflict' ? 'conflict-row' : ''; }
        function isStaged(status) { return ['Staged', 'Staged+Modified', 'Added'].includes(status); }
        function formatDate(iso) { return iso ? iso.split('T')[0] : ''; }

        // ── Resizable panels ──
        function startResizeSidebar(e) {
            isResizingSidebar.value = true;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            const startX = e.clientX;
            const startW = sidebarWidth.value;
            function onMove(ev) {
                const delta = ev.clientX - startX;
                const newW = Math.max(140, Math.min(400, startW + delta));
                sidebarWidth.value = newW;
            }
            function onUp() {
                isResizingSidebar.value = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        }

        function startResizeTree(e) {
            isResizingTree.value = true;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            const startX = e.clientX;
            const startW = treeWidth.value;
            function onMove(ev) {
                const delta = ev.clientX - startX;
                const newW = Math.max(120, Math.min(500, startW + delta));
                treeWidth.value = newW;
            }
            function onUp() {
                isResizingTree.value = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        }

        // ── Error Analysis ──
        function analyzeGitError(result) {
            const msg = (result.error || result.message || result.stderr || result.stdout || '').toLowerCase();
            const originalMsg = result.error || result.message || result.stderr || result.stdout || '';

            const patterns = [
                // Push errors
                { match: /failed to push some refs/i, hint: '⬆️ Cần kéo (Pull) trước khi đẩy (Push) do remote có commit mới.\n👉 Cách fix: Nhấn "Kéo về" (Pull) để đồng bộ, sau đó thử Push lại.' },
                { match: /(couldn't find remote ref|src refspec.*does not match any)/i, hint: '🔍 Không tìm thấy nhánh trên remote.\n👉 Cách fix: Kiểm tra tên nhánh hoặc dùng "git push --all"' },
                { match: /(permission denied|publickey)/i, hint: '🔑 Lỗi xác thực SSH key.\n👉 Cách fix: Kiểm tra SSH key đã được thêm vào GitHub/Gitea chưa.' },
                { match: /(authentication failed|auth failed)/i, hint: '🔑 Lỗi xác thực.\n👉 Cách fix: Kiểm tra lại token hoặc username/password trong Cài đặt.' },
                { match: /could not read from remote repository/i, hint: '🌐 Không thể kết nối remote.\n👉 Cách fix: Kiểm tra URL remote và kết nối mạng.' },
                { match: /remote.*already exists/i, hint: '📛 Remote đã tồn tại.\n👉 Cách fix: Dùng tên khác hoặc update URL remote hiện tại.' },

                // Pull errors
                { match: /(conflict|merge conflict)/i, hint: '⚠️ Xung đột (conflict) khi merge!\n👉 Cách fix: Mở Fork để giải quyết conflict thủ công, sau đó commit kết quả.' },
                { match: /(couldn't merge|automatic merge failed)/i, hint: '⚠️ Không thể tự động merge.\n👉 Cách fix: Giải quyết conflict thủ công.' },
                { match: /already up to date/i, hint: '✅ Remote đã đồng bộ, không có gì để kéo về.' },
                { match: /(not a git repository|fatal: not a git repository)/i, hint: '📂 Thư mục này chưa phải Git repository.\n👉 Cách fix: Nhấn "Tạo Git repo" để khởi tạo.' },

                // Commit errors
                { match: /(nothing to commit|no changes added)/i, hint: '📝 Không có thay đổi nào để commit.\n👉 Cách fix: Stage file trước (chọn checkbox) hoặc tạo thay đổi trong code.' },
                { match: /changes not staged for commit/i, hint: '📝 File chưa được stage.\n👉 Cách fix: Chọn checkbox bên cạnh file để stage, hoặc nhấn "Stage tất cả".' },
                { match: /nothing added to commit/i, hint: '📝 Chưa có file nào được stage.\n👉 Cách fix: Dùng "Stage tất cả" hoặc stage từng file.' },
                { match: /please tell me who you are/i, hint: '👤 Chưa cấu hình Git user.\n👉 Cách fix: Chạy lệnh:\ngit config user.email "email@example.com"\ngit config user.name "Tên của bạn"' },
                { match: /commit before pull/i, hint: '💾 Có commit local chưa được push.\n👉 Cách fix: Commit trước hoặc dùng "git stash" để tạm cất.' },

                // Push: no upstream
                { match: /(no upstream branch|no upstream|has no upstream)/i, hint: '🌿 Nhánh hiện tại chưa có upstream.\n👉 Đã tự động thêm --set-upstream. Lần sau Push sẽ hoạt động bình thường.' },

                // Branch errors
                { match: /(did not match any file|pathspec.*did not match)/i, hint: '🔍 Không tìm thấy file hoặc nhánh này.\n👉 Cách fix: Kiểm tra lại tên đường dẫn hoặc tên nhánh.' },
                { match: /(already exists|cannot create.*already)/i, hint: '📛 Đã tồn tại.\n👉 Cách fix: Dùng tên khác.' },
                { match: /(couldn't find|cannot find|not found)/i, hint: '🔍 Không tìm thấy.\n👉 Cách fix: Kiểm tra lại tên hoặc đường dẫn.' },

                // Stash errors
                { match: /no stash found/i, hint: '📦 Không có stash nào để phục hồi.\n👉 Cách fix: Dùng "Cất giữ" (Stash) trước để lưu thay đổi tạm thời.' },

                // Tag errors
                { match: /(is not a valid tag name|tag.*already)/i, hint: '🏷️ Tên tag không hợp lệ hoặc đã tồn tại.\n👉 Cách fix: Dùng tên không dấu cách, vd: v1.0.0 hoặc v1.0.0-beta' },

                // Checkout / Switch branch errors (local changes would be overwritten)
                { match: /your local changes to the following files would be overwritten by checkout/i, hint: '📝 Có thay đổi chưa commit sẽ bị ghi đè khi chuyển nhánh.\n👉 Cách fix: Commit trước (💾 Lưu commit) hoặc dùng "Cất giữ" (📦 Stash) để tạm cất thay đổi, sau đó chuyển nhánh.' },
                { match: /your local changes to the following files would be overwritten by merge/i, hint: '📝 Có thay đổi chưa commit sẽ bị ghi đè khi merge.\n👉 Cách fix: Commit trước hoặc dùng Stash để tạm cất thay đổi.' },

                // Detached HEAD / not on a branch
                { match: /(not currently on a branch|detached head|detached HEAD)/i, hint: '⚠️ Bạn đang ở trạng thái "Detached HEAD" — không ở trên nhánh nào.\n👉 Cách fix: Dùng "Chuyển nhánh" (switch) về nhánh cũ hoặc tạo nhánh mới tại đây: git switch -c ten-nhanh-moi' },
                { match: /(would be overwritten by checkout|local changes.*overwritten)/i, hint: '📝 Có thay đổi chưa commit sẽ bị ghi đè khi chuyển nhánh.\n👉 Cách fix: Commit trước (💾 Lưu commit) hoặc dùng "Cất giữ" (📦 Stash).' },

                // General
                { match: /has no commits yet/i, hint: '📂 Repository chưa có commit nào.\n👉 Cách fix: Tạo file mới, stage và commit lần đầu tiên.' },
                { match: /is beyond/i, hint: '⚠️ Lỗi không xác định.\n👉 Cách fix: Kiểm tra lại thao tác hoặc thử làm mới (Refresh).' },
            ];

            for (const p of patterns) {
                if (p.match.test(msg)) return p.hint;
            }

            // Show the actual error if nothing else matched
            if (originalMsg) {
                // Truncate long messages for display
                const display = originalMsg.length > 120 ? originalMsg.substring(0, 120) + '...' : originalMsg;
                return '⚠️ ' + display + '\n👉 Hãy kiểm tra lại thao tác hoặc commit/stage file trước khi thực hiện.';
            }

            // Generic fallback
            if (result.returncode === 128) return '🔒 Lỗi truy cập. Kiểm tra quyền và kết nối mạng.';
            if (result.returncode === 1 && msg.includes('fatal:')) return '❌ Lỗi Git nghiêm trọng. Kiểm tra thông báo lỗi bên trên.';
            if (result.returncode && result.returncode !== 0) return '⚠️ Lỗi không xác định (mã ' + result.returncode + '). Hãy thử làm mới hoặc kiểm tra terminal.';

            return '';
        }

        function formatDateVerbose(iso) {
            if (!iso) return '';
            try {
                const d = new Date(iso);
                const now = new Date();
                const diff = (now - d) / 1000;
                if (diff < 60) return 'Vừa xong';
                if (diff < 3600) return `${Math.floor(diff/60)} phút trước`;
                if (diff < 86400) return `${Math.floor(diff/3600)} giờ trước`;
                if (diff < 604800) return `${Math.floor(diff/86400)} ngày trước`;
                return d.toLocaleDateString('vi-VN', { day: 'numeric', month: 'short', year: 'numeric' });
            } catch (e) { return iso; }
        }

        function commitNodeClass(c) {
            // Assign colors based on hash for consistent coloring
            const hash = c.full_hash || c.hash || '';
            const colors = ['node-purple', 'node-blue', 'node-green', 'node-orange', 'node-red', 'node-cyan'];
            let sum = 0;
            for (let i = 0; i < hash.length && i < 8; i++) sum += hash.charCodeAt(i);
            return colors[sum % colors.length];
        }

        function showContextMenu(event, file) {
            contextMenu.value = { visible: true, x: event.clientX, y: event.clientY, file };
        }

        function openFileInExplorer(filePath) {
            // Open the file in Windows Explorer
            const fullPath = selectedProject.value.path + '\\' + filePath;
            try {
                const { shell } = require('electron'); // won't work in browser
            } catch(e) {}
            // Fallback: use command
            const cmd = `explorer /select,"${fullPath}"`;
            fetch('/api/dialogs/run-command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd }),
            }).catch(() => {});
            toast('Đã mở: ' + fullPath, 'info');
        }

        async function checkoutCommit(hash) {
            if (!confirm(`Checkout commit ${hash}?\n(trạng thái HEAD detached - bạn sẽ không ở trên nhánh nào)`)) return;
            try {
                const d = await gitCmd(selectedProject.value.id, 'custom', { command: `checkout ${hash}` });
                if (d.success) { toast(`Đã checkout ${hash}`, 'success'); await selectProject(selectedProject.value); }
                else toast('Checkout thất bại', 'error');
            } catch (e) { toast(e.message, 'error'); }
        }

        // ── Reset / Restore ──
        async function resetToCommit(hash, mode) {
            resetTarget.value = hash;
            showResetConfirm.value = true;
            showResetPanel.value = true;
            // Auto-trigger for quick button clicks
            if (mode === 'soft' || mode === 'mixed') {
                if (confirm(`⚠️ Reset ${mode} về commit ${hash}?\n\n` + (mode === 'soft' ? 'Giữ nguyên thay đổi (an toàn)' : 'Bỏ stage, giữ thay đổi trong file'))) {
                    await executeReset(mode);
                }
            } else if (mode === 'hard') {
                await confirmHardReset();
            }
        }

        async function executeReset(mode) {
            const target = resetTarget.value.trim();
            if (!target) { toast('Nhập commit hash hoặc nhánh', 'error'); return; }
            const modeNames = { soft: 'Soft', mixed: 'Mixed', hard: 'Hard' };
            resetResult.value = null;
            try {
                const d = await gitCmd(selectedProject.value.id, 'reset', { mode, target });
                resetResult.value = d;
                if (d.success) {
                    toast(`✅ Reset ${modeNames[mode] || mode} về ${target} thành công!`, 'success');
                    showResetConfirm.value = false;
                    showResetPanel.value = false;
                    await selectProject(selectedProject.value);
                } else {
                    toast('Reset thất bại', 'error');
                }
            } catch (e) { resetResult.value = { success: false, message: e.message }; }
        }

        async function confirmHardReset() {
            const target = resetTarget.value.trim();
            if (!target) { toast('Nhập commit hash hoặc nhánh', 'error'); return; }
            const msg = `⚠️⚠️⚠️ CẢNH BÁO: HARD RESET ⚠️⚠️⚠️\n\nBạn sắp mất TẤT CẢ thay đổi chưa commit!\n\nReset về: ${target}\n\nNhập "CONFIRM" để xác nhận:`;
            const confirm2 = prompt(msg);
            if (confirm2 === 'CONFIRM') {
                await executeReset('hard');
            } else {
                toast('Nhập "CONFIRM" để xác nhận Hard Reset', 'error');
            }
        }

        async function confirmRevert() {
            const target = resetTarget.value.trim();
            if (!target) { toast('Nhập commit hash', 'error'); return; }
            if (!confirm(`Tạo commit mới để hoàn tác (revert) commit ${target}?`)) return;
            resetResult.value = null;
            try {
                const d = await gitCmd(selectedProject.value.id, 'custom', { command: `revert --no-edit ${target}` });
                resetResult.value = d;
                if (d.success) {
                    toast(`✅ Đã revert commit ${target}!`, 'success');
                    showResetConfirm.value = false;
                    showResetPanel.value = false;
                    await selectProject(selectedProject.value);
                } else {
                    toast('Revert thất bại', 'error');
                }
            } catch (e) { resetResult.value = { success: false, message: e.message }; }
        }

        function copyText(text) {
            navigator.clipboard.writeText(text).then(() => toast('Đã copy', 'success')).catch(() => {});
        }

        // ── Select Working Directory ──
        async function selectWorkingDir() {
            try {
                const result = await api('/api/dialogs/select-folder', { method: 'POST' });
                const dir = result.path;
                if (!dir || result.cancelled) return;
                const exists = projects.value.find(p => osPathEqual(p.path, dir));
                if (exists) { await selectProject(exists); return; }
                await api('/api/projects', { method: 'POST', body: JSON.stringify({ clone_url: '', target_dir: dir, _local_path: dir }) });
                toast('Đã thêm dự án!', 'success');
                await loadProjects();
                const added = projects.value.find(p => osPathEqual(p.path, dir));
                if (added) await selectProject(added);
            } catch (e) { toast(e.message, 'error'); }
        }

        function osPathEqual(a, b) {
            return a.replace(/\\\\/g, '\\').toLowerCase() === b.replace(/\\\\/g, '\\').toLowerCase();
        }

        // ── Select Project ──
        async function selectProject(proj) {
            selectedProject.value = proj;
            navTab.value = 'home';
            showCommitPanel.value = false; showBranchPanel.value = false;
            commitMessage.value = ''; commitDescription.value = ''; diffContent.value = '';
            commitResult.value = null; branchResult.value = null; syncResult.value = null; syncing.value = null;
            viewingFile.value = ''; fileContent.value = ''; fileTree.value = [];

            projectStatus.value = { branch: '?', files: [], ahead: 0, behind: 0, has_conflict: false };
            commitLog.value = []; branches.value = []; remotes.value = [];

            try { const status = await api(`/api/projects/${proj.id}/status`); projectStatus.value = status; updateProjectStatus(proj.id, status); } catch (e) {}
            try { const log = await gitCmd(proj.id, 'log', { limit: 30 }); commitLog.value = Array.isArray(log) ? log : []; } catch (e) {}
            try { const g = await gitCmd(proj.id, 'graph', { limit: 50, all: true }); graphData.value = Array.isArray(g) ? g : []; } catch (e) { graphData.value = []; }
            // Fetch remote refs so remote branches appear
            try { await gitCmd(proj.id, 'fetch'); } catch (e) {}
            try { const bs = await gitCmd(proj.id, 'branch_list'); branches.value = Array.isArray(bs) ? bs : []; } catch (e) {}
            try { const rs = await gitCmd(proj.id, 'remote_list'); remotes.value = Array.isArray(rs) ? rs : []; } catch (e) {}
            loadFileTree();
            selectedBranch.value = projectStatus.value.branch || '';
        }

        function updateProjectStatus(id, status) {
            const p = projects.value.find(x => x.id === id);
            if (p) p.status_summary = { branch: status.branch, has_changes: status.files && status.files.length > 0, has_conflict: status.has_conflict || false };
        }

        async function refreshAll() {
            await loadProjects();
            if (selectedProject.value) await selectProject(selectedProject.value);
            toast('Đã làm mới', 'success');
        }

        // ── Init Git ──
        async function initGitRepo() {
            if (!selectedProject.value) return;
            initGitLoading.value = true; initResult.value = null;
            try {
                const data = await gitCmd(selectedProject.value.id, 'init');
                initResult.value = data;
                if (data.success) { toast('Đã tạo Git repo!', 'success'); await selectProject(selectedProject.value); }
            } catch (e) { initResult.value = { success: false, message: e.message }; }
            finally { initGitLoading.value = false; }
        }

        // ── File Tree ──
        // File tree state
        const dragOverPath = ref(null);

        async function loadFileTree() {
            if (!selectedProject.value || !isGitRepo.value) return;
            fileTreeLoading.value = true;
            try {
                const tree = await gitCmd(selectedProject.value.id, 'tree');
                fileTree.value = Array.isArray(tree) ? tree : [];
            } catch (e) { fileTree.value = []; }
            finally { fileTreeLoading.value = false; }
        }

        function isReadmeFile(path) {
            return path.toLowerCase().includes('readme');
        }

        function fileIcon(name) {
            const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
            const icons = {
                js: '🟨', ts: '🟦', py: '🐍', html: '🟧', css: '🟪', json: '{ }',
                md: '📝', txt: '📄', xml: '🔶', yml: '🔹', yaml: '🔹',
                sh: '⚡', bat: '⚡', ps1: '⚡', exe: '⚙️', dll: '⚙️',
                png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', svg: '🖼️',
                ico: '🖼️', woff: '🔤', woff2: '🔤', ttf: '🔤', eot: '🔤',
                pyc: '⚫', pyd: '⚫', so: '⚫', class: '☕', java: '☕',
            };
            return icons[ext] || (name.startsWith('.') ? '⚙️' : '📄');
        }
        function fileIconClass(name) {
            const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
            const classes = {
                js: 'js', ts: 'ts', py: 'py', html: 'html', css: 'css', json: 'json',
                md: 'md', xml: 'xml', yml: 'yml', yaml: 'yml',
                png: 'img', jpg: 'img', jpeg: 'img', gif: 'img', svg: 'img',
                pyc: 'bin', pyd: 'bin', so: 'bin', exe: 'bin', dll: 'bin',
                class: 'java', java: 'java',
            };
            return classes[ext] || (name.startsWith('.') ? 'hidden' : 'generic');
        }

        function onTreeItemClick(item) {
            if (item.type === 'dir') {
                // Toggle directory expansion by clicking again? For now just show content if possible
                return;
            }
            viewFileContent(item);
        }

        // ── Drag & Drop for file tree ──
        let draggedItem = null;
        function onTreeDragStart(event, item) {
            draggedItem = item;
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', item.path);
        }
        function onTreeDragOver(event, item) {
            if (!draggedItem || draggedItem.path === item.path) return;
            dragOverPath.value = item.path;
        }
        function onTreeDragLeave(event) {
            dragOverPath.value = null;
        }
        async function onTreeDrop(event, targetItem) {
            dragOverPath.value = null;
            if (!draggedItem || draggedItem.path === targetItem.path) {
                draggedItem = null;
                return;
            }
            // For git: move/rename file using git mv
            const src = draggedItem.path;
            let dest;
            if (targetItem.type === 'dir') {
                dest = targetItem.path + '/' + draggedItem.name;
            } else {
                // Target is a file — move to same dir with different name? Ask user via rename
                toast('Kéo thả: thả vào thư mục để di chuyển file vào đó', 'info');
                draggedItem = null;
                return;
            }
            if (!confirm(`Di chuyển "${src}" → "${dest}"?`)) {
                draggedItem = null;
                return;
            }
            try {
                const d = await gitCmd(selectedProject.value.id, 'custom', { command: `mv "${src}" "${dest}"` });
                if (d.success) {
                    toast(`✅ Đã di chuyển "${src}"`, 'success');
                    await loadFileTree();
                    await refreshStatus();
                } else {
                    toast('❌ Di chuyển thất bại: ' + (d.stderr || ''), 'error');
                }
            } catch (e) { toast(e.message, 'error'); }
            draggedItem = null;
        }

        async function viewFileContent(item) {
            if (item.type === 'dir') return;
            viewingFile.value = item.path;
            fileContentLoading.value = true;
            fileContent.value = '';
            try {
                const data = await gitCmd(selectedProject.value.id, 'read_file', { file: item.path });
                fileContent.value = data.content || '(empty file)';
            } catch (e) { fileContent.value = 'Error: ' + e.message; }
            finally { fileContentLoading.value = false; }
        }

        // ── Gitea ──
        async function fetchDashboardGiteaRepos() {
            if (!settings.value.gitea_server_url) return;
            giteaLoading.value = true;
            try { const data = await api('/api/gitea/repos'); giteaRepos.value = data.repos || []; }
            catch (e) { /* ignore */ }
            finally { giteaLoading.value = false; }
        }

        async function cloneGiteaRepo(repo) {
            const targetDir = 'C:\\Projects\\' + repo.name;
            giteaImporting.value = repo.id;
            try {
                const data = await api('/api/gitea/repos/import', { method: 'POST', body: JSON.stringify({ clone_url: repo.clone_url, target_dir: targetDir }) });
                toast(`Clone "${repo.name}" thành công!`, 'success');
                await loadProjects();
                const added = projects.value.find(p => p.path === targetDir);
                if (added) await selectProject(added);
            } catch (e) { toast(e.message, 'error'); }
            finally { giteaImporting.value = null; }
        }

        async function openGiteaTab() { addTab.value = 'gitea'; giteaImport.value = { targetDir: '' }; giteaImportProgress.value = ''; giteaImporting.value = null; await fetchDashboardGiteaRepos(); }
        async function fetchGiteaRepos() { giteaLoading.value = true; giteaError.value = ''; try { const d = await api('/api/gitea/repos'); giteaRepos.value = d.repos || []; } catch (e) { giteaError.value = e.message; } finally { giteaLoading.value = false; } }
        async function importGiteaRepo(repo) {
            let td = giteaImport.value.targetDir.trim() || 'C:\\Projects';
            giteaImporting.value = repo.id; giteaImportProgress.value = '';
            try { const d = await api('/api/gitea/repos/import', { method: 'POST', body: JSON.stringify({ clone_url: repo.clone_url, target_dir: td + '\\' + repo.name }) }); toast(`Clone OK`, 'success'); await loadProjects(); closeAddModal(); } catch (e) { giteaImportProgress.value = e.message; toast(e.message, 'error'); }
            finally { giteaImporting.value = null; }
        }

        // ── GitHub ──
        async function fetchDashboardGithubRepos() {
            githubLoading.value = true;
            githubError.value = '';
            try {
                const data = await api('/api/github/repos');
                githubRepos.value = data.repos || [];
            } catch (e) {
                githubError.value = e.message;
            } finally {
                githubLoading.value = false;
            }
        }

        async function cloneGithubRepo(repo) {
            const targetDir = 'C:\\Projects\\' + repo.name;
            githubImporting.value = repo.id;
            try {
                const data = await api('/api/github/repos/import', {
                    method: 'POST',
                    body: JSON.stringify({ clone_url: repo.clone_url, target_dir: targetDir })
                });
                toast(`Clone "${repo.name}" thành công!`, 'success');
                await loadProjects();
                const added = projects.value.find(p => p.path === targetDir);
                if (added) await selectProject(added);
            } catch (e) {
                toast(e.message, 'error');
            } finally {
                githubImporting.value = null;
            }
        }

        // ── Stage / Diff ──
        async function stageFile(fp) { try { await gitCmd(selectedProject.value.id, 'stage_file', { file: fp }); await refreshStatus(); } catch (e) { toast(e.message, 'error'); } }
        async function unstageFile(fp) { try { await gitCmd(selectedProject.value.id, 'unstage_file', { file: fp }); await refreshStatus(); } catch (e) { toast(e.message, 'error'); } }
        async function unstageAll() {
            const staged = projectStatus.value.files.filter(f => isStaged(f.status));
            for (const f of staged) { try { await gitCmd(selectedProject.value.id, 'unstage_file', { file: f.path }); } catch(e) {} }
            toast('Đã bỏ stage tất cả', 'success');
            await refreshStatus();
        }
        async function toggleStage(file) { if (isStaged(file.status)) await unstageFile(file.path); else await stageFile(file.path); }
        async function stageAll() { try { await gitCmd(selectedProject.value.id, 'stage_all'); toast('Stage all OK', 'success'); await refreshStatus(); } catch (e) { toast(e.message, 'error'); } }
        async function refreshStatus() {
            if (!selectedProject.value) return;
            try { const s = await api(`/api/projects/${selectedProject.value.id}/status`); projectStatus.value = s; updateProjectStatus(selectedProject.value.id, s); } catch (e) { projectStatus.value = { branch: '?', files: [], ahead: 0, behind: 0, has_conflict: false }; }
        }
        async function viewDiff(fp) { diffFile.value = fp; try { const d = await gitCmd(selectedProject.value.id, 'diff', { file: fp }); diffContent.value = d.content || '(empty)'; } catch (e) { diffContent.value = 'Error: ' + e.message; } }

        // ── Commit ──
        async function executeCommit() {
            if (!commitMessage.value.trim()) return;
            commitResult.value = null;
            try {
                let msg = commitMessage.value.trim();
                if (commitDescription.value.trim()) msg += '\n\n' + commitDescription.value.trim();
                const data = await gitCmd(selectedProject.value.id, 'commit', { message: msg });
                commitResult.value = data;
                if (data.success) {
                    toast('✅ Commit thành công!', 'success');
                    commitMessage.value = ''; commitDescription.value = '';
                    await refreshStatus();
                    const log = await gitCmd(selectedProject.value.id, 'log', { limit: 30 }); commitLog.value = Array.isArray(log) ? log : [];
                    // Auto push or offer to push
                    if (remotes.value.length > 0) {
                        if (autoPushAfterCommit.value) {
                            setTimeout(() => executePush(), 500);
                            toast('⬆️ Đang tự động đẩy lên remote...', 'info');
                        } else {
                            setTimeout(() => {
                                if (confirm('✅ Commit thành công!\n\n⬆️ Đẩy lên remote ngay bây giờ?')) {
                                    executePush();
                                }
                            }, 300);
                        }
                    }
                } else {
                    toast('Commit thất bại', 'error');
                }
            } catch (e) { commitResult.value = { success: false, message: e.message }; }
        }

        // ── Branch ──
        async function createBranch() {
            const name = newBranchName.value.trim(); if (!name) return;
            branchResult.value = null;
            try { const d = await gitCmd(selectedProject.value.id, 'branch_create', { name }); branchResult.value = d; newBranchName.value = ''; if (d.success) { toast('Tạo nhánh OK', 'success'); await refreshBranches(); } } catch (e) { branchResult.value = { success: false, message: e.message }; }
        }
        async function switchBranch(name) {
            branchResult.value = null;
            try { const d = await gitCmd(selectedProject.value.id, 'branch_switch', { name }); branchResult.value = d; if (d.success) { toast('Chuyển nhánh OK', 'success'); await selectProject(selectedProject.value); } } catch (e) { branchResult.value = { success: false, message: e.message }; }
        }
        async function deleteBranch(name) {
            if (!confirm(`Xóa nhánh "${name}"?`)) return;
            branchResult.value = null;
            try { const d = await gitCmd(selectedProject.value.id, 'branch_delete', { name }); branchResult.value = d; if (d.success) { toast('Xóa nhánh OK', 'success'); await refreshBranches(); } } catch (e) { branchResult.value = { success: false, message: e.message }; }
        }
        async function refreshBranches() { if (!selectedProject.value) return; try { const b = await gitCmd(selectedProject.value.id, 'branch_list'); branches.value = Array.isArray(b) ? b : []; } catch (e) { branches.value = []; } }
        async function refreshLog() { if (!selectedProject.value) return; try { const l = await gitCmd(selectedProject.value.id, 'log', { limit: 30 }); commitLog.value = Array.isArray(l) ? l : []; } catch (e) { commitLog.value = []; } }

        // ── Merge ──
        function mergeBranchInto(name) {
            mergeSourceBranch.value = name;
        }
        async function executeMerge() {
            if (!mergeSourceBranch.value || !selectedProject.value) return;
            merging.value = true; branchResult.value = null;
            try {
                const d = await gitCmd(selectedProject.value.id, 'merge', { branch: mergeSourceBranch.value });
                branchResult.value = d;
                if (d.success) {
                    toast('✅ Merge thành công!', 'success');
                    const mergedBranch = mergeSourceBranch.value;
                    mergeSourceBranch.value = '';
                    await refreshBranches(); await refreshStatus(); await refreshLog();
                    // Suggest deleting the merged branch
                    if (!mergedBranch.startsWith('remotes/') && mergedBranch !== projectStatus.value.branch) {
                        setTimeout(() => {
                            if (confirm(`🧹 Nhánh "${mergedBranch}" đã được merge.\n\nXóa nhánh "${mergedBranch}" để dọn dẹp?`)) {
                                deleteBranch(mergedBranch);
                            }
                        }, 500);
                    }
                }
                else toast('Merge thất bại', 'error');
            } catch (e) { branchResult.value = { success: false, message: e.message }; }
            finally { merging.value = false; }
        }

        // ── Releases ──
        async function fetchReleases() {
            if (!selectedProject.value) return;
            try {
                const tags = await gitCmd(selectedProject.value.id, 'tag_list');
                releases.value = Array.isArray(tags) ? tags.map(t => ({ name: t, full_hash: '', message: '' })) : [];
                // Get details for each tag
                for (const r of releases.value) {
                    try {
                        const log = await gitCmd(selectedProject.value.id, 'log', { limit: 1, branch: `tags/${r.name}` });
                        if (Array.isArray(log) && log.length > 0) {
                            r.full_hash = log[0].full_hash || log[0].hash || '';
                            r.date = log[0].date || '';
                            r.author = log[0].author || '';
                        }
                    } catch (e) { /* tag may not have commit info */ }
                    // Try to get tag message
                    try {
                        const d = await gitCmd(selectedProject.value.id, 'custom', { command: `tag -l ${r.name} --format="%(contents)"` });
                        if (d.success && d.stdout) r.message = d.stdout.substring(0, 500);
                    } catch (e) {}
                }
            } catch (e) { releases.value = []; }
        }
        async function createRelease() {
            const tag = newReleaseTag.value.trim(); const desc = newReleaseDesc.value.trim();
            if (!tag) return;
            releaseResult.value = null;
            try {
                const d = await gitCmd(selectedProject.value.id, 'tag_create', { name: tag, message: desc || `Release ${tag}` });
                releaseResult.value = d;
                if (d.success) {
                    newReleaseTag.value = ''; newReleaseDesc.value = '';
                    await fetchReleases();

                    // Auto push tag to remote
                    if (remotes.value.length > 0) {
                        const pushResult = await gitCmd(selectedProject.value.id, 'push_tag', { tag, remote: 'origin' });
                        if (pushResult.success) {
                            toast(`✅ Tag ${tag} đã được đẩy lên remote!`, 'success');
                        } else {
                            toast('⚠️ Đẩy tag thất bại', 'error');
                        }
                    }

                    // Auto create Release on Gitea
                    if (selectedProject.value.gitea_remote) {
                        try {
                            const rel = await api(`/api/projects/${selectedProject.value.id}/gitea-release`, {
                                method: 'POST',
                                body: JSON.stringify({ tag_name: tag, name: tag, body: desc || `Release ${tag}` })
                            });
                            if (rel.success) {
                                toast(`🎉 Đã tạo Release trên Gitea!`, 'success');
                            }
                        } catch (e) {
                            // Gitea release creation is optional, don't block
                            console.warn('Gitea release creation failed:', e.message);
                        }
                    }
                }
                else toast('Tạo release thất bại', 'error');
            } catch (e) { releaseResult.value = { success: false, message: e.message }; }
        }
        async function deleteRelease(tag) {
            if (!confirm(`Xóa release "${tag}"?`)) return;
            releaseResult.value = null;
            try {
                const d = await gitCmd(selectedProject.value.id, 'tag_delete', { name: tag });
                releaseResult.value = d;
                if (d.success) { toast('Đã xóa release', 'success'); await fetchReleases(); }
            } catch (e) { releaseResult.value = { success: false, message: e.message }; }
        }
        async function pushReleaseTag(tag) {
            releaseResult.value = null;
            try {
                const d = await gitCmd(selectedProject.value.id, 'push_tag', { tag, remote: 'origin' });
                releaseResult.value = d;
                if (d.success) toast(`✅ Tag ${tag} đã được đẩy lên remote!`, 'success');
                else toast('⚠️ Đẩy tag thất bại', 'error');
            } catch (e) { releaseResult.value = { success: false, message: e.message }; }
        }

        // ── Sync ──
        async function executePush(force = false) {
            if (!selectedProject.value) return;
            syncing.value = 'push'; syncResult.value = null;
            try {
                const resp = await fetch(`/api/projects/${selectedProject.value.id}/git/push`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ force })
                });
                const d = await resp.json();
                syncResult.value = d;
                if (d.success) {
                    toast('✅ Push thành công!', 'success');
                    await refreshStatus();
                } else {
                    const stderr = (d.stderr || d.stdout || '').toLowerCase();
                    // Auto pull & retry on non-fast-forward
                    if (stderr.includes('non-fast-forward') || stderr.includes('rejected')) {
                        if (!force && confirm('⚠️ Remote có commit mới hơn local.\n\n➡️ Nhấn OK để Pull về trước, sau đó tự động Push lại.\n❌ Nhấn Cancel để huỷ.')) {
                            toast('⏳ Đang kéo về và hợp nhất...', 'info');
                            const pullResp = await fetch(`/api/projects/${selectedProject.value.id}/git/pull`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({})
                            });
                            const pullResult = await pullResp.json();
                            if (pullResult.success) {
                                toast('✅ Pull thành công! Đang đẩy lên lại...', 'success');
                                await executePush(false);
                                return;
                            } else {
                                // Pull failed (maybe conflict), show the push error instead
                                syncResult.value = d;
                                toast('❗ Pull thất bại — có thể do xung đột. Kiểm tra kết quả để biết thêm chi tiết.', 'error');
                            }
                        } else if (!force) {
                            toast('Push bị từ chối', 'error');
                        }
                    }
                }
            } catch (e) { syncResult.value = { success: false, message: e.message }; }
            finally { syncing.value = null; }
        }
        async function executePull() { syncing.value = 'pull'; syncResult.value = null; try { const d = await gitCmd(selectedProject.value.id, 'pull'); syncResult.value = d; if (d.success) toast('Pull OK', 'success'); await refreshStatus(); await refreshLog(); } catch (e) { syncResult.value = { success: false, message: e.message }; } finally { syncing.value = null; } }
        async function executeFetch() { syncing.value = 'fetch'; syncResult.value = null; try { const d = await gitCmd(selectedProject.value.id, 'fetch'); syncResult.value = d; if (d.success) toast('Fetch OK', 'success'); await refreshStatus(); } catch (e) { syncResult.value = { success: false, message: e.message }; } finally { syncing.value = null; } }
        async function executeStashPush() { try { const d = await gitCmd(selectedProject.value.id, 'stash_push'); if (d.success) { toast('Stash OK', 'success'); await refreshStatus(); } } catch (e) { toast(e.message, 'error'); } }

        // ── Remote ──
        async function updateRemoteUrl(name, url) {
            try { const d = await gitCmd(selectedProject.value.id, 'custom', { command: `remote set-url ${name} ${url}` }); if (d.success) { toast('Đã cập nhật remote', 'success'); const rs = await gitCmd(selectedProject.value.id, 'remote_list'); remotes.value = Array.isArray(rs) ? rs : []; } } catch (e) { toast(e.message, 'error'); }
        }
        async function addRemote() {
            const n = newRemoteName.value.trim() || 'origin'; const u = newRemoteUrl.value.trim();
            if (!u) { toast('Nhập URL', 'error'); return; }
            try { const d = await gitCmd(selectedProject.value.id, 'remote_add', { name: n, url: u }); if (d.success) { toast('Đã thêm remote', 'success'); newRemoteUrl.value = ''; const rs = await gitCmd(selectedProject.value.id, 'remote_list'); remotes.value = Array.isArray(rs) ? rs : []; } } catch (e) { toast(e.message, 'error'); }
        }
        async function removeRemoteByName(name) {
            if (!confirm(`Xóa remote "${name}"?`)) return;
            try { const d = await gitCmd(selectedProject.value.id, 'remote_remove', { name }); if (d.success) { toast('Đã xóa remote', 'success'); const rs = await gitCmd(selectedProject.value.id, 'remote_list'); remotes.value = Array.isArray(rs) ? rs : []; } } catch (e) { toast(e.message, 'error'); }
        }
        async function createAndPushRemote(platform) {
            if (!selectedProject.value) return;
            creatingRemote.value = platform;
            try {
                const d = await api(`/api/projects/${selectedProject.value.id}/create-remote`, { method: 'POST', body: JSON.stringify({ platform, private: false, description: selectedProject.value.name }) });
                if (d.success) {
                    toast(d.message, 'success');
                    const rs = await gitCmd(selectedProject.value.id, 'remote_list');
                    remotes.value = Array.isArray(rs) ? rs : [];
                    // For 'both', also create remote on the other platform if needed
                    if (platform === 'both') {
                        // Update project's remote URLs from the response
                        if (d.github_url && selectedProject.value) selectedProject.value.github_remote = d.github_url;
                        if (d.gitea_url && selectedProject.value) selectedProject.value.gitea_remote = d.gitea_url;
                    }
                    const pushConfirm = platform === 'both' ? 'Push code lên cả GitHub và Gitea ngay?' : `Push code lên ${platform} ngay?`;
                    if (confirm(pushConfirm)) await executePush();
                }
                else toast(d.error || 'Thất bại', 'error');
            } catch (e) { toast(e.message, 'error'); }
            finally { creatingRemote.value = null; }
        }

        // ── Fork / Delete / PR / Blame / Rebase ──
        async function openInFork() { if (!selectedProject.value) return; try { await api(`/api/projects/${selectedProject.value.id}/open`, { method: 'POST' }); toast('Đã mở Fork', 'success'); } catch (e) { toast(e.message, 'error'); } }
        async function deleteProject() {
            if (!selectedProject.value) return;
            const rml = confirm(`Xóa "${selectedProject.value.name}"?\nOK = xóa cả thư mục`);
            try { await api(`/api/projects/${selectedProject.value.id}`, { method: 'DELETE', body: JSON.stringify({ remove_local: rml }) }); toast('Đã xóa', 'success'); selectedProject.value = null; await loadProjects(); } catch (e) { toast(e.message, 'error'); }
        }
        function createPullRequest() {
            const proj = selectedProject.value;
            if (!proj) return;
            // Determine remote URL and construct compare URL
            const remoteUrl = proj.github_remote || proj.gitea_remote;
            if (!remoteUrl) { toast('Chưa có remote GitHub/Gitea', 'error'); return; }
            const branch = projectStatus.value.branch || 'main';
            let url = '';
            if (proj.github_remote) {
                // GitHub: https://github.com/owner/repo/compare/main...feature?expand=1
                const m = remoteUrl.match(/github\.com[:\/](.+?)\/(.+?)(?:\.git)?$/);
                if (m) url = `https://github.com/${m[1]}/${m[2]}/compare/${branch}?expand=1`;
            } else if (proj.gitea_remote) {
                // Gitea: http://server/owner/repo/compare/main...feature
                const m = remoteUrl.match(/https?:\/\/[^\/]+(.+?)\.git$/);
                if (m) url = remoteUrl.replace(/\.git$/, '') + `/compare/${branch}?expand=1`;
            }
            if (url) { window.open(url, '_blank'); toast('Đã mở trang tạo Pull Request', 'success'); }
            else toast('Không thể xác định URL remote', 'error');
        }
        function blameFile(filePath) {
            if (!selectedProject.value || !settings.value.fork_path) { toast('Cần cấu hình Fork trong Cài đặt', 'error'); return; }
            // Open Fork with blame for the file
            try { api(`/api/projects/${selectedProject.value.id}/open`, { method: 'POST', body: JSON.stringify({ action: 'blame', file: filePath }) }); toast('Đã mở Fork - Blame', 'success'); } catch (e) { toast(e.message, 'error'); }
        }
        async function rebaseBranch(branch) {
            if (!selectedProject.value) return;
            const target = projectStatus.value.branch || 'main';
            const msg = `⚠️ CẢNH BÁO: Rebase là thao tác NGUY HIỂM!\n\nSẽ rebase nhánh "${branch}" lên "${target}".\nChỉ thực hiện nếu bạn hiểu rõ hậu quả.\n\nNhập "REBASE" để xác nhận:`;
            const confirm2 = prompt(msg);
            if (confirm2 !== 'REBASE') { toast('Nhập "REBASE" để xác nhận', 'error'); return; }
            try {
                const d = await gitCmd(selectedProject.value.id, 'custom', { command: `rebase ${target} ${branch}` });
                if (d.success) { toast(`✅ Rebase ${branch} lên ${target} thành công!`, 'success'); await selectProject(selectedProject.value); }
                else toast('Rebase thất bại', 'error');
            } catch (e) { toast(e.message, 'error'); }
        }

        // ── Clone / Create ──
        async function submitClone() {
            const f = cloneForm.value; if (!f.url || !f.targetDir) { toast('Nhập URL và thư mục', 'error'); return; }
            cloning.value = true; cloneProgress.value = '';
            try { const d = await api('/api/projects', { method: 'POST', body: JSON.stringify({ clone_url: f.url, target_dir: f.targetDir }) }); if (d.lines) cloneProgress.value = d.lines.join('\n'); toast('Clone OK', 'success'); await loadProjects(); closeAddModal(); const a = projects.value.find(p => p.path === f.targetDir); if (a) await selectProject(a); navTab.value = 'home'; } catch (e) { cloneProgress.value = e.message; toast(e.message, 'error'); } finally { cloning.value = false; }
        }
        async function submitCreate() {
            const f = createForm.value; if (!f.name || !f.targetDir) { toast('Nhập tên và thư mục', 'error'); return; }
            if (!f.github && !f.gitea) { toast('Chọn ít nhất một nền tảng', 'error'); return; }
            creating.value = true; createProgress.value = '';
            try { const d = await api('/api/projects', { method: 'POST', body: JSON.stringify(f) }); if (d.lines) createProgress.value = d.lines.join('\n'); toast('Tạo OK', 'success'); await loadProjects(); closeAddModal(); navTab.value = 'home'; } catch (e) { createProgress.value = e.message; toast(e.message, 'error'); } finally { creating.value = false; }
        }

        // ── Settings ──
        function openSettings() { showAddModal.value = false; showSettingsModal.value = true; tokenResults.value = { github: null, gitea: null, password: null }; }
        function closeSettings() { showSettingsModal.value = false; }
        async function checkToken(platform) {
            const token = platform === 'github' ? formSettings.value.github_token : formSettings.value.gitea_token;
            if (!token) return;
            checking.value[platform] = true; tokenResults.value[platform] = null;
            try { const d = await api('/api/settings/check-token', { method: 'POST', body: JSON.stringify({ platform, token }) }); tokenResults.value[platform] = d.valid; if (d.valid) toast(`Token ${platform} OK (${d.info?.username || ''})`, 'success'); else toast('Token không hợp lệ', 'error'); } catch (e) { tokenResults.value[platform] = false; toast(e.message, 'error'); } finally { checking.value[platform] = false; }
        }
        async function checkGiteaPassword() {
            const { gitea_server_url, gitea_username, gitea_password } = formSettings.value;
            if (!gitea_server_url || !gitea_username || !gitea_password) return;
            checking.value.password = true; tokenResults.value.password = null;
            try { const d = await api('/api/settings/check-token', { method: 'POST', body: JSON.stringify({ platform: 'gitea_password', username: gitea_username, password: gitea_password }) }); tokenResults.value.password = d.valid; if (d.valid) toast(`Login OK (${d.info?.username || ''})`, 'success'); else toast('Sai user/pass', 'error'); } catch (e) { tokenResults.value.password = false; toast(e.message, 'error'); } finally { checking.value.password = false; }
        }
        async function saveSettings() {
            // Only send fields that the user actually changed (skip placeholder values)
            const payload = { ...formSettings.value };
            if (payload.github_token === '••••••••') delete payload.github_token;
            if (payload.gitea_token === '••••••••') delete payload.gitea_token;
            if (payload.gitea_username === '••••••••') delete payload.gitea_username;
            if (payload.gitea_password === '••••••••') delete payload.gitea_password;
            try { await api('/api/settings', { method: 'POST', body: JSON.stringify(payload) }); toast('Đã lưu', 'success'); await loadSettings(); closeSettings(); } catch (e) { toast(e.message, 'error'); }
        }
        function openAddModal() { showSettingsModal.value = false; showAddModal.value = true; addTab.value = 'clone'; cloneForm.value = { url: '', targetDir: '' }; createForm.value = { name: '', description: '', private: false, github: true, gitea: true, targetDir: '' }; cloneProgress.value = ''; createProgress.value = ''; }
        function closeAddModal() { showAddModal.value = false; }

        async function browseDir(form) {
            try { const r = await api('/api/dialogs/select-folder', { method: 'POST' }); const d = r.path; if (!d || r.cancelled) return; if (form === 'clone') cloneForm.value.targetDir = d; else if (form === 'create') createForm.value.targetDir = d; else if (form === 'gitea') giteaImport.value.targetDir = d; }
            catch (e) { const d = prompt('Đường dẫn:'); if (d) { if (form === 'clone') cloneForm.value.targetDir = d; else if (form === 'create') createForm.value.targetDir = d; } }
        }
        function browseFile() { const f = prompt('Đường dẫn fork.exe:'); if (f) formSettings.value.fork_path = f; }

        // ── Toast ──
        function toast(message, type = 'info') {
            const c = document.getElementById('toast-container');
            const el = document.createElement('div');
            el.className = `toast ${type}`; el.textContent = message;
            c.appendChild(el);
            setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(100%)'; el.style.transition = 'all 0.3s ease'; setTimeout(() => el.remove(), 300); }, 3500);
        }

        // ── OTA Release Management ──
        const otaReleaseTag = ref('v1.0.1');
        const otaAppVerCode = ref(1);
        const otaFwVerCode = ref(1);
        const otaApkPath = ref('d:\\Documents\\PlatformIO\\Tdriver\\TYMAP\\app\\build\\outputs\\apk\\debug\\app-debug.apk');
        const otaBinPath = ref('d:\\Documents\\PlatformIO\\Tdriver\\TYMAP\\firmware\\esp32_s3_gc9a01\\.pio\\build\\esp32-s3-devkitc-1\\firmware.bin');
        const otaOledBinPath = ref('d:\\Documents\\PlatformIO\\Tdriver\\TYMAP\\firmware\\esp32_c3_oled\\.pio\\build\\esp32-c3-devkitm-1\\firmware.bin');
        const otaChangelog = ref('• Cập nhật ứng dụng TYMAP & Firmware ESP32 mới.\n• Tối ưu hóa Bluetooth BLE kết nối ổn định.');
        const otaLoading = ref(false);
        const otaDetecting = ref(false);
        const otaResult = ref(null);

        async function autoDetectOtaAssets() {
            if (!selectedProject.value) return;
            otaDetecting.value = true;
            try {
                const resp = await fetch(`/api/projects/${selectedProject.value.id}/ota-detect`);
                const data = await resp.json();
                if (data.apk_path) otaApkPath.value = data.apk_path;
                if (data.bin_path) otaBinPath.value = data.bin_path;
                if (data.oled_bin_path) otaOledBinPath.value = data.oled_bin_path;
                if (data.suggested_tag) otaReleaseTag.value = data.suggested_tag;
                if (data.suggested_app_code) otaAppVerCode.value = data.suggested_app_code;
                if (data.suggested_fw_code) otaFwVerCode.value = data.suggested_fw_code;
                if (data.changelog) otaChangelog.value = data.changelog;
                toast('🔍 Đã tự động phát hiện các file build!', 'success');
            } catch (e) {
                console.warn('OTA detect error:', e);
            } finally {
                otaDetecting.value = false;
            }
        }

        async function browseOtaFile(type) {
            try {
                const resp = await fetch('/api/browse-file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: type })
                });
                const data = await resp.json();
                if (data.file_path) {
                    if (type === 'apk') otaApkPath.value = data.file_path;
                    if (type === 'bin') otaBinPath.value = data.file_path;
                    if (type === 'oled_bin') otaOledBinPath.value = data.file_path;
                }
            } catch (e) {
                toast('Lỗi duyệt file: ' + e.message, 'error');
            }
        }

        async function submitOtaRelease() {
            if (!selectedProject.value) return;
            if (!otaReleaseTag.value.trim()) {
                toast('Vui lòng nhập Tag Name (ví dụ: v1.0.1)', 'error');
                return;
            }
            otaLoading.value = true;
            otaResult.value = null;
            try {
                const resp = await fetch(`/api/projects/${selectedProject.value.id}/ota-release`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        tag_name: otaReleaseTag.value.trim(),
                        release_name: otaReleaseTag.value.trim(),
                        changelog: otaChangelog.value,
                        apk_path: otaApkPath.value,
                        bin_path: otaBinPath.value,
                        oled_bin_path: otaOledBinPath.value,
                        app_version_code: otaAppVerCode.value,
                        fw_version_code: otaFwVerCode.value
                    })
                });
                const data = await resp.json();
                if (resp.ok && data.success) {
                    otaResult.value = { success: true, logs: data.logs };
                    toast('🚀 Đã phát hành OTA thành công!', 'success');
                    refreshStatus();
                } else {
                    otaResult.value = { success: false, error: data.error || 'Lỗi phát hành OTA' };
                    toast(data.error || 'Lỗi phát hành OTA', 'error');
                }
            } catch (e) {
                otaResult.value = { success: false, error: e.message };
            } finally {
                otaLoading.value = false;
            }
        }

        // ── Return ──
        return {
            navTab, goHome,
            projects, filteredProjects, selectedProject, searchQuery, selectedBranch,
            projectStatus, commitLog, branches, remotes, remoteMap,
            syncResult, syncing,
            fileTree, fileTreeLoading, viewingFile, fileContent, fileContentLoading, isReadmeFile, viewFileContent,
            fileIcon, fileIconClass, onTreeItemClick,
            dragOverPath, onTreeDragStart, onTreeDragOver, onTreeDragLeave, onTreeDrop,
            showCommitPanel, showBranchPanel,
            commitMessage, commitDescription, commitResult, stagedCount, autoPushAfterCommit,
            newBranchName, branchResult, mergeSourceBranch, merging, mergeBranchInto, executeMerge,
            newRemoteName, newRemoteUrl, creatingRemote,
            initGitLoading, initResult, isGitRepo, gitConnectionClass,
            showReleasesPanel, newReleaseTag, newReleaseDesc, releases, releaseResult,
            fetchReleases, createRelease, deleteRelease, pushReleaseTag,
            otaReleaseTag, otaAppVerCode, otaFwVerCode, otaApkPath, otaBinPath, otaOledBinPath, otaChangelog, otaLoading, otaDetecting, otaResult,
            browseOtaFile, submitOtaRelease, autoDetectOtaAssets,
            graphData, graphRowHeight, graphSvgWidth, selectedCommit, contextMenu, commitNodeClass, formatDateVerbose, showContextMenu, openFileInExplorer, checkoutCommit, fetchGraph, renderGraphSegments,
            parseRefs, authorColor, authorInitial,
            sidebarWidth, treeWidth, isResizingSidebar, isResizingTree,
            startResizeSidebar, startResizeTree,
            showResetPanel, resetTarget, showResetConfirm, resetResult,
            resetToCommit, executeReset, confirmHardReset, confirmRevert,
            diffContent, diffFile,
            showAddModal, showSettingsModal, addTab,
            cloneForm, createForm, cloning, creating, cloneProgress, createProgress,
            settings, formSettings, checking, tokenResults,
            giteaRepos, giteaRepoCount, giteaLoading, giteaError, giteaImporting, giteaImportProgress, giteaImport,
            githubRepos, filteredGithubRepos, githubSearchQuery, githubLoading, githubError, githubImporting, fetchDashboardGithubRepos, cloneGithubRepo,
            selectProject, selectWorkingDir, filterProjects, statusClass, statusRowClass, isStaged, formatDate, copyText, analyzeGitError,
            refreshAll, refreshStatus, refreshLog, refreshBranches,
            stageFile, unstageFile, toggleStage, stageAll, unstageAll, viewDiff,
            executeCommit, createBranch, switchBranch, deleteBranch,
            executePush, executePull, executeFetch, executeStashPush,
            addRemote, updateRemoteUrl, removeRemoteByName, createAndPushRemote,
            openInFork, deleteProject, createPullRequest, blameFile, rebaseBranch,
            submitClone, submitCreate,
            openGiteaTab, fetchGiteaRepos, importGiteaRepo, cloneGiteaRepo, fetchDashboardGiteaRepos,
            initGitRepo,
            openSettings, closeSettings, checkToken, checkGiteaPassword, saveSettings,
            openAddModal, closeAddModal, browseDir, browseFile,
            toast,
        };
    },
});

app.mount('#app');
