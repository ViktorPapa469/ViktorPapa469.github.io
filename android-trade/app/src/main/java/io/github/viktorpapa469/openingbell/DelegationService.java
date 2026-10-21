package io.github.viktorpapa469.openingbell;

/**
 * Lets Chrome hand Opening Bell's web notifications to this app, so they show under the app's own name and icon,
 * and asks for Android's notification permission when the page requests it.
 */
public class DelegationService extends com.google.androidbrowserhelper.trusted.DelegationService {
}
