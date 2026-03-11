import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';

const VIEW_TYPE = 'agentSidebar.chatView';
const FOCUS_COMMAND = 'agentSidebar.focus';
const CONTAINER_COMMAND = 'workbench.view.extension.agentSidebar';

type ViteManifest = Record<
  string,
  {
    file: string;
    css?: string[];
  }
>;

export function activate(context: vscode.ExtensionContext): void {
  const provider = new AgentSidebarProvider(context);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(VIEW_TYPE, provider, {
      webviewOptions: {
        retainContextWhenHidden: true,
      },
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(FOCUS_COMMAND, async () => {
      await vscode.commands.executeCommand(CONTAINER_COMMAND);
    }),
  );
}

export function deactivate(): void {}

class AgentSidebarProvider implements vscode.WebviewViewProvider {
  constructor(private readonly context: vscode.ExtensionContext) {}

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'webview-dist')],
    };

    webviewView.webview.html = this.getHtml(webviewView.webview);
  }

  private getHtml(webview: vscode.Webview): string {
    const distRoot = vscode.Uri.joinPath(this.context.extensionUri, 'webview-dist');
    const manifestPath = path.join(
      this.context.extensionPath,
      'webview-dist',
      '.vite',
      'manifest.json',
    );

    if (!fs.existsSync(manifestPath)) {
      return this.getMissingBuildHtml(webview);
    }

    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as ViteManifest;
    const entry = manifest['webview/src/main.tsx'] ?? manifest['src/main.tsx'];

    if (!entry) {
      return this.getMissingBuildHtml(webview);
    }

    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(distRoot, entry.file));
    const styleUris = (entry.css ?? []).map((cssFile) =>
      webview.asWebviewUri(vscode.Uri.joinPath(distRoot, cssFile)),
    );
    const nonce = getNonce();

    const styles = styleUris
      .map((uri) => `<link rel="stylesheet" href="${uri.toString()}">`)
      .join('\n');

    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; img-src ${webview.cspSource} https: data:; font-src ${webview.cspSource}; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src ws://127.0.0.1:8765;"
    />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    ${styles}
    <title>Agent Sidebar</title>
  </head>
  <body>
    <div id="root"></div>
    <script nonce="${nonce}">
      window.__VSCODE_API__ = acquireVsCodeApi();
    </script>
    <script type="module" nonce="${nonce}" src="${scriptUri.toString()}"></script>
  </body>
</html>`;
  }

  private getMissingBuildHtml(webview: vscode.Webview): string {
    const nonce = getNonce();

    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';"
    />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Agent Sidebar</title>
  </head>
  <body style="margin:0;padding:16px;background:var(--vscode-sideBar-background);color:var(--vscode-editor-foreground);font-family:var(--vscode-font-family);">
    <h2 style="margin:0 0 8px; font-size:14px;">Webview bundle missing</h2>
    <p style="margin:0; line-height:1.6; color:var(--vscode-descriptionForeground);">
      Run <code>npm run build</code> in the extension folder to generate the React webview bundle.
    </p>
  </body>
</html>`;
  }
}

function getNonce(length = 32): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let value = '';

  for (let index = 0; index < length; index += 1) {
    value += alphabet.charAt(Math.floor(Math.random() * alphabet.length));
  }

  return value;
}
