#!/usr/bin/env bash
# Build on a Linux cloud server; no always-on computer is needed.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
tools_dir="${PHONEPILOT_BUILD_TOOLS:-$project_dir/.build-tools}"
for tool in java javac curl unzip; do
  command -v "$tool" >/dev/null || { echo "缺少 $tool。Ubuntu 可安装 openjdk-17-jdk curl unzip。" >&2; exit 1; }
done
mkdir -p "$tools_dir/downloads" "$tools_dir/sdk/cmdline-tools"
export ANDROID_HOME="$tools_dir/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_USER_HOME="$tools_dir/gradle-cache"

if [[ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]]; then
  curl --fail --location --retry 2 --connect-timeout 15 --max-time 600 \
    https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip \
    --output "$tools_dir/downloads/commandline.zip"
  unzip -q -o "$tools_dir/downloads/commandline.zip" -d "$tools_dir/sdk-unpack"
  mv "$tools_dir/sdk-unpack/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
fi
if [[ ! -x "$tools_dir/gradle-8.11.1/bin/gradle" ]]; then
  curl --fail --location --retry 2 --connect-timeout 15 --max-time 600 \
    https://services.gradle.org/distributions/gradle-8.11.1-bin.zip \
    --output "$tools_dir/downloads/gradle.zip"
  curl --fail --location --connect-timeout 15 --max-time 60 \
    https://services.gradle.org/distributions/gradle-8.11.1-bin.zip.sha256 \
    --output "$tools_dir/downloads/gradle.sha256"
  expected="$(tr -d '\r\n ' < "$tools_dir/downloads/gradle.sha256")"
  [[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || { echo 'Gradle 校验值格式异常' >&2; exit 1; }
  printf '%s  %s\n' "$expected" "$tools_dir/downloads/gradle.zip" | sha256sum --check --status
  unzip -q -o "$tools_dir/downloads/gradle.zip" -d "$tools_dir"
fi
echo '请阅读并按需接受 Android SDK 许可，然后继续构建。'
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" 'platforms;android-35' 'build-tools;35.0.0'
cd "$project_dir"
"$tools_dir/gradle-8.11.1/bin/gradle" --no-daemon :app:assembleDebug :app:lintDebug
echo "APK: $project_dir/app/build/outputs/apk/debug/app-debug.apk"
