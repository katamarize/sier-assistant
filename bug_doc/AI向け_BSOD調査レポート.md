# AI向け調査レポート: Ollama実行中のBSOD解析

## 目的

OllamaでローカルLLM推論中に発生したBSODの原因分析。

## 環境

  項目     内容
  -------- ----------------------
  OS       Windows 11 (26100系)
  GPU      RTX 3070 8GB
  Driver   NVIDIA 591.86
  CUDA     13.1
  LLM      Ollama
  Model    Qwen3:8B

## 症状

-   推論中に画面がブラックアウト
-   PC電源は継続
-   Win+Ctrl+Shift+B後にPOST→Windowsログオン画面
-   イベントビューアー:
    -   Kernel-Power 41
    -   EventLog 6008
    -   volmgr 162
-   BugCheck:
    -   0x133 DPC_WATCHDOG_VIOLATION

## WinDbg要点

    BugCheck: DPC_WATCHDOG_VIOLATION (133)
    DPC_TIMEOUT_TYPE: DPC_QUEUE_EXECUTION_TIMEOUT_EXCEEDED

スタックには複数の `nvlddmkm` フレームが存在。

    nvlddmkm+...
    nvlddmkm+...
    ...

メモリ関連:

    Memory manager detected 1 instance(s) of page corruption
    target is likely to have memory corruption.

その他: - BAD_PAGES_DETECTED: 1 - PAGE_NOT_ZERO_0x133 - PROCESS_NAME:
System

## 現時点での考察

### 仮説A

NVIDIAドライバー(nvlddmkm.sys)がDPC内でハングしWatchdog発火。

### 仮説B

RAMまたはメモリサブシステム起因でページ破損が発生し、その結果GPUドライバーが異常終了。

### 仮説C

CUDA/Ollamaと現行ドライバーの組み合わせによる不具合。

## 未確認事項

-   XMP/EXPO有無
-   RAM型番
-   MemTest86結果
-   GPU温度・消費電力
-   GPUベンチで再現するか
-   Driver Ver.変更で改善するか

## 推奨調査順

1.  MEMORY.DMPをさらに詳細解析（!thread, !dpcs, lmvm nvlddmkm, !pte等）
2.  DDU後にドライバー再導入（必要なら安定版へロールバック）
3.  MemTest86実施
4.  GPUストレステスト
5.  Ollama/CUDA再現試験

## AIへの依頼

以下を重点的に評価してください。 - nvlddmkmが一次原因か二次障害か -
PAGE_NOT_ZEROおよびpage corruptionとの因果関係 - 0x133とMemory
corruptionの優先度 - NVIDIA Driver 591.86既知不具合の有無 - RTX3070 +
Ollama + Qwen3:8B構成との関連性 - 追加で実施すべきWinDbgコマンド
