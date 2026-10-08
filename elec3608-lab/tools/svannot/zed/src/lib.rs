//! Zed extension that attaches the `svannot` annotation language server to
//! Verilog and SystemVerilog buffers.
//!
//! Install as a dev extension (`zed: install dev extension`, pointing at this
//! directory).  The Verilog extension must also be installed, since it supplies
//! the language definitions and the tree-sitter grammar; this extension only
//! adds a server.
//!
//! ## Finding the server
//!
//! Zed works in worktree-relative paths, and the worktree root is whatever the
//! user opened.  That is `Desktop/ELEC3608` in one session and
//! `Desktop/ELEC3608/elec3608-lab` in another, so a single hard-coded relative
//! path is wrong half the time -- and the failure is a bare
//! "No such file or directory" from the spawn, with no hint that the path was
//! the problem.
//!
//! So instead of guessing, probe: `Worktree::read_text_file` reports whether a
//! path exists, so walk a list of plausible locations and use the first that
//! resolves.  `settings.json` can still override everything with
//! `lsp.svannot.binary.path`.

use zed_extension_api::{self as zed, LanguageServerId, Worktree};

/// Must match the `[language_servers.<id>]` key in extension.toml.
const LANGUAGE_SERVER_ID: &str = "svannot";

/// Where `run.sh` might live, relative to the worktree root, most likely first.
const CANDIDATES: &[&str] = &[
    "tools/svannot/run.sh",              // worktree root IS elec3608-lab
    "elec3608-lab/tools/svannot/run.sh", // worktree root is the parent
    "svannot/run.sh",
    "src/tools/svannot/run.sh",
];

/// A binary on `$PATH` also works, for anyone who would rather symlink it.
const PATH_BINARY: &str = "svannot-lsp";

struct SvannotExtension;

impl SvannotExtension {
    /// Locate `run.sh`, or explain every place we looked.
    ///
    /// `Worktree::read_text_file` only accepts *worktree-relative* paths: given
    /// an absolute one the host panics with "absolute path not allowed" rather
    /// than returning `Err`, which aborts the whole extension.  So the probe is
    /// relative-only, and only the value handed back to Zed is absolute (which
    /// is fine -- `Command::command` is spawned as-is).
    fn find_server(worktree: &Worktree) -> zed::Result<String> {
        let root = worktree.root_path();
        let mut tried = Vec::new();

        for rel in CANDIDATES {
            if worktree.read_text_file(rel).is_ok() {
                return Ok(format!("{root}/{rel}"));
            }
            tried.push(format!("{root}/{rel}"));
        }

        // Fall back to a symlinked binary on $PATH.
        if let Some(found) = worktree.which(PATH_BINARY) {
            return Ok(found);
        }

        Err(format!(
            "svannot: could not find run.sh. Looked for [{}] and for `{}` on $PATH. \
             Fix by setting \"lsp\": {{\"svannot\": {{\"binary\": {{\"path\": \
             \"/absolute/path/to/tools/svannot/run.sh\"}}}}}} in settings.json.",
            tried.join(", "),
            PATH_BINARY
        ))
    }
}

impl zed::Extension for SvannotExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        language_server_id: &LanguageServerId,
        worktree: &Worktree,
    ) -> zed::Result<zed::Command> {
        if language_server_id.as_ref() != LANGUAGE_SERVER_ID {
            return Err(format!("unknown language server `{language_server_id}`"));
        }

        Ok(zed::Command {
            command: Self::find_server(worktree)?,
            args: vec!["--stdio".to_string()],
            env: vec![],
        })
    }
}

zed::register_extension!(SvannotExtension);
