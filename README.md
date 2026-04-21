# WwiseSnap

A desktop tool that saves and restores parameter snapshots of Wwise objects via WAAPI. Select any object in Wwise, save its current state as a snapshot, and restore it at any time — without touching the project manually.

## Features

- **Save snapshots** of any Wwise object's parameters in one click
- **Restore** saved parameters back to the object at any time
- **Detail view** organized by tabs matching Wwise's own UI layout — General, Routing, Positioning, Advanced, and more
- Captures scalar properties, override flags, randomizer (Modifier) values, attenuation curves, and references (Output Bus, Attenuation ShareSet, etc.)
- Snapshots are stored in a local SQLite database and persist across sessions
- **Export / Import** snapshots as JSON files for backup or sharing
- Connects to Wwise automatically on launch via WAAPI

## Requirements

- Wwise 2025.x with WAAPI enabled
- [`sk-wwise-mcp`](https://github.com/sokolkreshnik/sk-wwise-mcp) installed at `~/sk-wwise-mcp`
- Python 3.10+

## Setup

### 1. Enable WAAPI in Wwise

**Wwise Launcher → Wwise → Settings → Enable Wwise Authoring API**

### 2. Run WwiseSnap

```
python main.py
```

WwiseSnap connects to Wwise automatically on launch. Make sure Wwise is open before starting.

## Usage

1. Select an object in the Wwise Project Explorer
2. In WwiseSnap, click **Save** to capture the current parameter state
3. Make changes in Wwise as needed
4. Select the saved snapshot and click **Restore** to revert to the saved state

Snapshots can be renamed, deleted, exported to JSON, or imported from JSON.

## Known Limitations

- 3D Position data is excluded from snapshots — Wwise does not expose waypoint data via WAAPI, so partial restores would be misleading
- Attenuation RTPCs are also excluded (WAAPI curve-write limitation)
- Restoring a reference property (e.g. Output Bus) requires the referenced object to exist in the current project

---

> **한국어 설명은 아래에 있습니다.**

---

## 한국어 설명

Wwise 오브젝트의 파라미터 상태를 스냅샷으로 저장하고 복원하는 데스크탑 도구입니다. Wwise에서 오브젝트를 선택한 뒤 현재 상태를 저장해두고, 언제든지 한 번에 복원할 수 있습니다.

## 주요 기능

- Wwise 오브젝트의 파라미터를 **스냅샷으로 저장**
- 저장된 파라미터를 오브젝트에 **복원**
- Wwise UI 구성과 동일한 탭 구조의 **상세 뷰** — General, Routing, Positioning, Advanced 등
- 스칼라 프로퍼티, Override 플래그, Randomizer(Modifier) 값, Attenuation 커브, 레퍼런스(Output Bus, Attenuation ShareSet 등) 캡처
- 스냅샷은 로컬 SQLite 데이터베이스에 저장되어 세션 종료 후에도 유지
- 스냅샷 **Export / Import** (JSON) 지원
- 실행 시 WAAPI로 Wwise에 자동 연결

## 요구 사항

- Wwise 2025.x (WAAPI 활성화 필요)
- [`sk-wwise-mcp`](https://github.com/sokolkreshnik/sk-wwise-mcp) (`~/sk-wwise-mcp` 경로에 설치)
- Python 3.10 이상

## 설치 방법

### 1. Wwise WAAPI 활성화

**Wwise Launcher → Wwise → Settings → Enable Wwise Authoring API**

### 2. WwiseSnap 실행

```
python main.py
```

Wwise가 열려있는 상태에서 실행하면 자동으로 연결됩니다.

## 사용 방법

1. Wwise Project Explorer에서 오브젝트 선택
2. WwiseSnap에서 **Save** 클릭 → 현재 파라미터 상태 저장
3. Wwise에서 파라미터 수정
4. 저장된 스냅샷 선택 후 **Restore** 클릭 → 저장 시점의 상태로 복원

스냅샷 이름 변경, 삭제, JSON Export/Import 가능합니다.

## 알려진 제한 사항

- 3D Position 데이터는 스냅샷에서 제외됩니다 — WAAPI를 통해 웨이포인트 데이터에 접근할 수 없어 부분 복원 시 오동작할 수 있기 때문입니다
- Attenuation RTPC도 동일한 이유로 제외됩니다 (WAAPI 커브 쓰기 제한)
- 레퍼런스 프로퍼티(Output Bus 등) 복원 시 참조 오브젝트가 현재 프로젝트에 존재해야 합니다
