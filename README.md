WwiseSnap: Professional Parameter Snapshot Manager

  WwiseSnap은 Wwise 오브젝트의 복잡한 파라미터 상태를 한 번의 클릭으로 저장하고 복원할 수 있는 프리셋 관리 도구입니다.

  핵심 기능 (Key Features)

   - 정밀한 파라미터 스냅샷: 볼륨, 피치, LPF/HPF 등 사운드 오브젝트의 핵심 속성을 즉시 저장하고
     복원합니다.
   - 어테뉴에이션 커브 지원: Distance 기반의 Volume, Filter, Spread, Focus 커브 데이터를 완벽하게
     시각화하고 다른 오브젝트에 이식할 수 있습니다.

     시작하기 (Getting Started)

  1. 사전 준비
   - Wwise가 실행 중이어야 합니다.
   - Project Settings -> External Control에서 Enable WAAPI가 활성화되어 있어야 합니다 (기본 포트:
     8080).

  2. 설치 및 실행
   - Releases (https://github.com/jaewon-sung/WwiseSnap/releases) 탭에서 최신 버전의 WwiseSnap.zip을
     다운로드합니다.
   - 압축을 풀고 WwiseSnap.exe를 실행합니다.
   - 상단 [Connect] 버튼을 눌러 Wwise와 연결합니다.

   - 사용 방법 (Usage)

   1. 저장(Save): Wwise에서 오브젝트를 선택하고, WwiseSnap 왼쪽의 SAVE NEW -> All 버튼을 누릅니다.
   2. 복원(Restore): 리스트에서 원하는 스냅샷을 선택(iOS 블루 하이라이트)하고, RESTORE SELECTED -> All
      버튼을 누릅니다.
   3. 개별 관리: 특정 탭(Attenuation 등) 하단의 버튼을 통해 원하는 항목만 골라서 복원할 수도 있습니다.

  기술적 제한 사항 (Known Limitations)

  현재 버전은 데이터 무결성과 시스템 안정성을 최우선으로 고려하여 제작되었습니다.
   - RTPC 및 Effects: 복원의 안정성을 위해 이번 버전에서는 지원하지 않습니다. (추후 업데이트 예정)
   - Dual-Shelf Filter: WAAPI의 쓰기 제한으로 인해 복원 대상에서 제외됩니다.
