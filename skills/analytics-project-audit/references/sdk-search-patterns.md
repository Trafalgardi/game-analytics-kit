# Search patterns for analytics, ads and IAP code

Search source and config only. Skip generated and vendor folders: Unity `Library/`,
`Temp/`, `obj/`, `Logs/`; Android `build/`, `.gradle/`; iOS `Pods/`, `DerivedData/`;
JS `node_modules/`; Flutter `.dart_tool/`. Start with package manifests (what is
installed), then call sites (what is sent), then constants (names), then assets (names
stored in data).

Example with ripgrep (any equivalent search works):

```
rg -n --glob "*.cs" -e "ReportEvent|LogEvent|NewDesignEvent|CustomEvent|TrackEvent" Assets
rg -n --glob "*.{kt,java}" -e "reportEvent|logEvent" app/src
```

## Package manifests

| Stack | Files |
| --- | --- |
| Unity | `Packages/manifest.json`, `Packages/packages-lock.json`, `Assets/Plugins/**`, `**/Editor/*Dependencies.xml` (External Dependency Manager), `ProjectSettings/ProjectSettings.asset` (scripting define symbols) |
| Android | `build.gradle(.kts)`, `settings.gradle`, `gradle/libs.versions.toml`, `AndroidManifest.xml` |
| iOS | `Podfile`, `Podfile.lock`, `Package.swift`, `Package.resolved`, `Info.plist` |
| Flutter | `pubspec.yaml`, `pubspec.lock` |
| React Native | `package.json`, lock file, `ios/Podfile`, `android/app/build.gradle` |

## Analytics SDK calls

| SDK | Unity C# | Android (Kotlin/Java) | iOS (Swift) | Flutter / RN |
| --- | --- | --- | --- | --- |
| AppMetrica | `AppMetrica.ReportEvent`, `AppMetrica.Activate`, `ReportRevenue`, `ReportAdRevenue`, `SetUserProfileID`, `ReportUserProfile` | `AppMetrica.reportEvent`, `YandexMetrica.reportEvent`, `reportRevenue`, `reportAdRevenue`, `setUserProfileID` | `AppMetrica.reportEvent(name:`, `YMMYandexMetrica.reportEvent` | `AppMetrica.reportEvent` |
| Firebase / GA4 | `FirebaseAnalytics.LogEvent`, `SetUserProperty`, `SetUserId` | `logEvent(`, `Firebase.analytics`, `setUserProperty` | `Analytics.logEvent(`, `Analytics.setUserProperty` | `FirebaseAnalytics.instance.logEvent`, `analytics().logEvent` |
| GameAnalytics | `GameAnalytics.NewDesignEvent`, `NewProgressionEvent`, `NewResourceEvent`, `NewAdEvent`, `NewBusinessEvent`, `NewErrorEvent` | `GameAnalytics.addDesignEvent`, `addProgressionEvent`, ... | `GameAnalytics.addDesignEvent` | plugin equivalents |
| devtodev | `DTDAnalytics.CustomEvent`, `DTDAnalytics.LevelUp`, `DTDAnalytics.RealCurrencyPayment`, `DTDAnalytics.AdImpression` | `DTDAnalytics.customEvent` | `DTDAnalytics.customEvent` | — |
| Amplitude | `Amplitude.Instance.logEvent` | `amplitude.track(` | `amplitude.track(` | `track(` |
| ByteBrew | `ByteBrew.NewCustomEvent`, `ByteBrew.TrackAdEvent`, `ByteBrew.NewProgressionEvent` | — | — | — |
| Unity Analytics / UGS | `Analytics.CustomEvent` (legacy), `AnalyticsService.Instance.RecordEvent`, `CustomData` | — | — | — |
| Adjust / AppsFlyer | `Adjust.trackEvent`, `AppsFlyer.sendEvent` | `Adjust.trackEvent`, `AppsFlyerLib.getInstance().logEvent` | `Adjust.trackEvent`, `AppsFlyerLib.shared().logEvent` | plugin equivalents |
| Facebook | `FB.LogAppEvent` | `AppEventsLogger` | `AppEvents.shared.logEvent` | — |

## Wrapper and constants

Most games wrap SDKs. Search for: `AnalyticsManager`, `AnalyticsService`, `IAnalytics`,
`GameAnalyticsService` (project facades may reuse SDK names), `TrackEvent`, `SendEvent`,
`LogEvent`, `ReportEvent`, `EventName`, `AnalyticsEvents`, `AnalyticsParams`,
`const string` inside classes whose name contains `Event`, `Param`, `Analytics`.
Then find every caller of the wrapper's public methods (a code index, "find usages", or
a text search for the method name). Also look for:

- parameters added to every event (days since install, session count, balance);
- providers the wrapper fans out to, and per-provider masks;
- compile flags or runtime switches that disable analytics (dev builds, consent, editor);
- names stored in serialized assets (`.prefab`, `.asset`, `.unity`, JSON configs,
  remote config) — search those files for event-like `snake_case` strings;
- dynamic names (`"level_" + id`, string interpolation) — find the builder and list the
  possible values.

## Ads and mediation

| Area | Patterns |
| --- | --- |
| Google Mobile Ads (AdMob) | `MobileAds.Initialize`, `InterstitialAd.Load`, `RewardedAd.Load`, `OnAdPaid`, `OnPaidEvent`, `AdValue`, `OnAdFullScreenContentOpened`, `OnAdFullScreenContentFailed`, `setOnPaidEventListener`, `paidEventHandler`, `onPaidEvent` |
| AppLovin MAX | `MaxSdk.`, `MaxSdkCallbacks.*.OnAdRevenuePaidEvent`, `OnAdDisplayedEvent`, `OnAdLoadFailedEvent` |
| ironSource / LevelPlay | `IronSource.Agent`, `IronSourceEvents.onImpressionDataReadyEvent`, `LevelPlay` |
| Unity Ads | `Advertisement.Load`, `Advertisement.Show`, `IUnityAdsShowListener` |
| Game-side | placement constants, cooldown timers, "no ads" ownership checks, reward callbacks, timeouts around show/load |

For each format, find where it is requested, loaded, shown, closed, rewarded, failed and
paid, and which of those moments send an event.

## In-app purchases

| Stack | Patterns |
| --- | --- |
| Unity IAP | `UnityPurchasing`, `IStoreListener`, `IDetailedStoreListener`, `ProcessPurchase`, `OnPurchaseFailed`, `ConfirmPendingPurchase`, `RestoreTransactions` |
| Google Play Billing | `BillingClient`, `onPurchasesUpdated`, `acknowledgePurchase`, `consumeAsync` |
| StoreKit | `SKPaymentTransactionObserver`, `Transaction.updates`, `Product.purchase` |
| Flutter / RN | `in_app_purchase`, `purchaseStream`, `react-native-iap` |

Check where revenue is reported (SDK revenue call vs custom event) so the plan does not
double-count revenue.

## Crashes, errors, performance

`Crashlytics`, `FirebaseCrashlytics`, AppMetrica crash reporting (enabled by default in
its SDK — check config), `Application.logMessageReceived` / `LogCallback` forwarding
exceptions as events, `ReportError`, `ANR` watchdogs; FPS or frame-time sampling, loading
stopwatch steps, device RAM / tier detection.

## Other engines

- Godot: `Engine.get_singleton("...")` for native analytics plugins, autoload scripts
  named `Analytics*`.
- Unreal: `FAnalytics`, `IAnalyticsProvider`, `UAnalyticsBlueprintLibrary::RecordEvent`,
  Blueprint nodes "Record Event" (search `.uasset` names if no text source).
- Native C++ / custom engines: search for the SDK's C API or JNI bridge names.
