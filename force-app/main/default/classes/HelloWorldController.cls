public with sharing class HelloWorldController {
  @AuraEnabled(cacheable=true)
  public static String getGreeting(String name) {
    if (String.isBlank(name)) {
      return 'Hello, World!';
    }
    return 'Hello, ' + String.escapeSingleQuotes(name) + '!';
  }

  @AuraEnabled(cacheable=false)
  public static String getCurrentDateTime() {
    return DateTime.now().format('EEEE, MMMM dd, yyyy \'at\' h:mm a');
  }
}
