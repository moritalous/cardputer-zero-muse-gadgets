# 実機セットアップ手順（CardputerZero）

上から順に進めてください。各ステップの最後にある **報告してほしいもの** を返してもらえると、うまくいかなかったときに原因を絞り込めます。

## 0. 準備

- CardputerZero（Wi-Fi に接続済み）
- Muse アプリ（iOS / Android）にログイン済みのスマホ
- SDK トークン: [gadgets.muse.ai → Account → SDK tokens](https://gadgets.muse.ai/settings/sdk-tokens) で発行（`mgst_…`）。先に [SDK Terms](https://gadgets.muse.ai/sdk-terms) を確認してください
- CardputerZero の「Settings」で SSH を有効にし、Mac から `ssh zero@<CardputerZeroのIP>` で入れる状態にする

## 1. 実機の状態を確認する

```bash
cat /etc/os-release
python3 --version
bluetoothctl show
groups
```

**報告してほしいもの:** 4 つのコマンドの出力（特に `bluetoothctl show` の `Powered:` と `Roles:` / `LE` の有無）

`Powered: no` / `PowerState: off-blocked` のときは Bluetooth が rfkill で止められています。次で有効にします:

```bash
sudo rfkill unblock bluetooth
bluetoothctl power on
bluetoothctl show | grep -E "Powered|PowerState"   # Powered: yes / PowerState: on になれば OK
```

> Muse SDK のペアリングは Bluetooth LE を使います。ここで BLE が使えないと分かった場合は、別の方法（他の Linux 機でペアリングして状態をコピーする方法が SDK のドキュメントにあります）を検討します。

## 2. Muse Gadgets SDK を入れてペアリングする

ログインユーザー（CardputerZero の標準イメージでは `zero`）で実行してください（Muse から実行されるコマンドがこのユーザー権限で動きます。アプリもこのユーザーのグループでサービスのソケットに接続します）。

```bash
curl -fsSL https://raw.githubusercontent.com/facebookincubator/muse-gadget-sdk/main/linux/install.sh -o install.sh
less install.sh   # 中身を確認
```

トークンがシェルの履歴に残らないように、画面に表示せず読み込んでから渡します:

```bash
read -rs MUSE_TOKEN && bash install.sh --sdk-token "$MUSE_TOKEN"; unset MUSE_TOKEN
```

インストーラーが「pairing is open」と表示したら、スマホの Muse アプリで:

1. Settings → Devices → **Developer mode** をオン
2. Settings → Devices → **Add Device**（右上の +）→ `MuseGadgetXXXXXX` を選ぶ
3. コミュニティデバイスの警告が出たら、自分の端末であることを確認して続行
4. Wi-Fi を聞かれたら表示されたネットワークを選ぶ（パスワード不要）

ペアリングの受付は 10 分です。やり直すときは `sudo musegadget pair`。

確認:

```bash
sudo musegadget info
sudo musegadget doctor
sudo journalctl -u musegadget -n 50 --no-pager
musegadget send-user-msg --wait 60 "こんにちは、聞こえますか？"
```

**報告してほしいもの:**
- `doctor` の出力
- ログに `registered with the Muse` が出たかどうか
- `send-user-msg` の返答が表示されたか（`Permission denied` などのエラーが出たらその全文）

※ ログやエラー全文にトークンは含まれませんが、念のため `mgst_` で始まる文字列が含まれていないか確認してから送ってください。

## 3. アプリ（.deb）を入れる

Mac でビルドして転送します:

```bash
cd cardputer-zero-muse-gadgets
uv run scripts/build_deb.py
scp dist/cz-muse-gadget_0.1.0_arm64.deb zero@<CardputerZeroのIP>:/tmp/
```

CardputerZero で（`apt` 経由で入れると、依存パッケージ（Pillow・numpy・日本語フォント）も一緒に入ります）:

```bash
sudo apt install /tmp/cz-muse-gadget_0.1.0_arm64.deb
sudo journalctl -u musegadget | grep -i commands   # cardputer.screen.show などが読み込まれたか
```

インストール時にログインユーザー（uid 1000）を `video` / `input` グループに追加するので、**一度再起動**してください。

### GitHub Releases から直接入れる（Mac を使わない方法）

タグ `v*` を push すると、GitHub Actions が `.deb` を作って Releases に添付します。CardputerZero で:

```bash
curl -fL -o ~/cz-muse-gadget_arm64.deb https://github.com/moritalous/cardputer-zero-muse-gadgets/releases/latest/download/cz-muse-gadget_arm64.deb
sudo apt install ~/cz-muse-gadget_arm64.deb
```

（`/tmp` は 177MB の RAM 領域なので、ダウンロード先はホームにしています）

## 4. 起動して試す

ランチャーから「Muse Gadget」を開きます。うまく開かない場合は、SSH から直接起動してログを見ます:

```bash
/usr/share/APPLaunch/bin/cz-muse-gadget --debug-keys
# 別の SSH セッションで
tail -f /tmp/czmuse.log
```

試してほしいこと:

1. 英数でメッセージを送る → 返答が表示されるか
2. Tab でかなモードにして `konnichiha` と打つ → 「こんにちは」になるか
3. ↑↓ でスクロールできるか（矢印キーが Fn との組み合わせの場合も含めて）
4. スマホの Muse アプリで「CardputerZero の画面に『テスト』と表示して」と頼む → ポップアップが出るか
5. 「CardputerZero のバッテリー残量は？」と聞く

**報告してほしいもの:**
- 画面の写真（またはうまくいかなかった項目）
- `/tmp/czmuse.log` の中身
- `--debug-keys` で出た、矢印・Esc・Tab・Fn 組み合わせのキーコード（例: `czmuse: key code=103`）

## アンインストール

```bash
sudo apt remove cz-muse-gadget        # アプリだけ消す
bash install.sh --uninstall           # SDK も消す（--purge でペアリング情報も削除）
```
