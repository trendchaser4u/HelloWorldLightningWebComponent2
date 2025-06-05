import { LightningElement, track } from "lwc";
import getGreeting from "@salesforce/apex/HelloWorldController.getGreeting";
import getCurrentDateTime from "@salesforce/apex/HelloWorldController.getCurrentDateTime";

export default class HelloWorld extends LightningElement {
  
  @track greeting = "Hello, World!";
  @track currentDateTime = "";
  @track userName = "";

  connectedCallback() {
    this.loadCurrentDateTime();
  }

  handleNameChange(event) {
    this.userName = event.target.value;
  }

  async handleGetGreeting() {
    try {
      this.greeting = await getGreeting({ name: this.userName });
    } catch (error) {
      this.greeting = "Error: " + (error.body?.message || error.message);
    }
  }

  async loadCurrentDateTime() {
    try {
      this.currentDateTime = await getCurrentDateTime();
    } catch (error) {
      this.currentDateTime = "Error loading date/time";
    }
  }
}
